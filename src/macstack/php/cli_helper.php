<?php
// cli_helper.php - Custom helper for macstack inspection and seed deployment

error_reporting(0);

$runtimeDir = getenv("MACSTACK_RUNTIME_DIR") ?: (getenv("HOME") . "/.local/share/macstack");
$qtypeStackDir = $runtimeDir . "/qtype_stack";

// Ensure working directory is api/public so relative requires inside MoodleEmulation work cleanly
if (file_exists($qtypeStackDir . "/api/public")) {
    chdir($qtypeStackDir . "/api/public");
}

require_once $qtypeStackDir . "/api/config.php";
require_once $qtypeStackDir . "/api/vendor/autoload.php";
require_once $qtypeStackDir . "/api/emulation/MoodleEmulation.php";
require_once $qtypeStackDir . "/api/util/StackQuestionLoader.php";
require_once $qtypeStackDir . "/api/util/StackIframeHolder.php";
require_once $qtypeStackDir . "/api/dtos/StackGradingResponse.php";
require_once $qtypeStackDir . "/api/util/StackPlotReplacer.php";
require_once $qtypeStackDir . "/api/util/StackSeedHelper.php";
require_once $qtypeStackDir . "/stack/cas/keyval.class.php";

use api\util\StackQuestionLoader;
use api\util\StackIframeHolder;
use api\util\StackPlotReplacer;
use api\util\StackSeedHelper;

function macstack_handle_request($uri) {
    header("Content-Type: application/json; charset=UTF-8");

    if ($uri === "/macstack/health") {
        echo json_encode([
            "ok" => true,
            "status" => "healthy",
            "stack_version" => "2025102100",
            "maxima_version" => "5.50.0"
        ]);
        exit(0);
    }

    $raw = file_get_contents("php://input");
    $data = json_decode($raw, true) ?: [];

    if ($uri === "/macstack/vars") {
        macstack_handle_vars($data);
    } else if ($uri === "/macstack/seeds") {
        macstack_handle_seeds($data);
    } else if ($uri === "/grade") {
        macstack_handle_grade($data);
    } else {
        http_response_code(404);
        echo json_encode(["error" => "Endpoint not found: $uri"]);
        exit(0);
    }
}

function macstack_probe_xml_cas_errors(string $xml, $options = null, $seed = 1): array {
    $probedErrors = [];
    libxml_use_internal_errors(true);
    $sxe = simplexml_load_string($xml);
    if ($sxe === false) {
        return $probedErrors;
    }

    $qNode = null;
    if ($sxe->getName() === 'question' && (string)$sxe['type'] === 'stack') {
        $qNode = $sxe;
    } else {
        $matches = $sxe->xpath("//question[@type='stack']");
        if (!empty($matches)) {
            $qNode = $matches[0];
        }
    }

    if (!$qNode) {
        return $probedErrors;
    }

    // Collect input names so PRT feedbackvariables and nodes know valid student inputs
    $inputNames = [];
    if (isset($qNode->input)) {
        foreach ($qNode->input as $inp) {
            $name = trim((string)$inp->name);
            if ($name !== '') {
                $inputNames[] = $name;
            }
        }
    }

    // Helper to extract line and col from error text
    $extractCoords = function(string $err): array {
        $line = null;
        $col = null;
        if (preg_match('/\(At about line\s+(\d+)\s+character\s+(\d+)\.?\)/i', $err, $m)) {
            $line = (int)$m[1];
            $col = (int)$m[2];
        }
        return [$line, $col];
    };

    // Helper to add probed error
    $addError = function(string $field, string $msg) use (&$probedErrors, $extractCoords) {
        $msg = trim($msg);
        if ($msg === '') return;
        list($line, $col) = $extractCoords($msg);
        $probedErrors[] = [
            "field" => $field,
            "message" => $msg,
            "line" => $line,
            "col" => $col,
        ];
    };

    // 1. Probe questionvariables
    $qvars = isset($qNode->questionvariables->text) ? (string)$qNode->questionvariables->text : (string)($qNode->questionvariables ?? "");
    if (trim($qvars) !== '') {
        try {
            $kv = new \stack_cas_keyval($qvars, $options, $seed, 'questionvariables');
            if (!$kv->get_valid()) {
                $errs = $kv->get_errors(false, 'strings');
                foreach ($errs as $err) {
                    $addError('questionvariables', (string)$err);
                }
            }
        } catch (\Throwable $e) {
            $addError('questionvariables', $e->getMessage());
        }
    }

    // 2. Probe PRTs
    if (isset($qNode->prt)) {
        foreach ($qNode->prt as $prt) {
            $prtName = trim((string)$prt->name);
            if ($prtName === '' && isset($prt['name'])) {
                $prtName = (string)$prt['name'];
            }

            // PRT feedbackvariables
            $fbVars = isset($prt->feedbackvariables->text) ? (string)$prt->feedbackvariables->text : (string)($prt->feedbackvariables ?? "");
            if (trim($fbVars) !== '') {
                $fvField = "prt:{$prtName}:feedbackvariables";
                try {
                    $fkv = new \stack_cas_keyval($fbVars, $options, $seed, $fvField);
                    if (!$fkv->get_valid($inputNames)) {
                        $errs = $fkv->get_errors(false, 'strings');
                        foreach ($errs as $err) {
                            $addError($fvField, (string)$err);
                        }
                    }
                } catch (\Throwable $e) {
                    $addError($fvField, $e->getMessage());
                }
            }

            // PRT nodes
            if (isset($prt->node)) {
                $idx = 0;
                foreach ($prt->node as $node) {
                    $nodeName = trim((string)$node->name);
                    if ($nodeName === '') {
                        $nodeName = (string)$idx;
                    }
                    $idx++;

                    // sans and tans
                    foreach (['sans', 'tans'] as $sub) {
                        $expr = trim((string)($node->$sub ?? ""));
                        if ($expr !== '') {
                            $nodeField = "prt:{$prtName}:node:{$nodeName}:{$sub}";
                            try {
                                $ast = \stack_ast_container_silent::make_from_teacher_source($expr, $nodeField);
                                if (!$ast->get_valid()) {
                                    $errs = $ast->get_errors();
                                    if (is_array($errs)) {
                                        foreach ($errs as $err) {
                                            $addError($nodeField, (string)$err);
                                        }
                                    } else if (!empty($errs)) {
                                        $addError($nodeField, (string)$errs);
                                    }
                                }
                            } catch (\Throwable $e) {
                                $addError($nodeField, $e->getMessage());
                            }
                        }
                    }
                }
            }
        }
    }

    // 3. Probe CASText fields if probed_errors is empty or to catch CASText syntax errors
    $ctFields = [
        'questiontext' => isset($qNode->questiontext->text) ? (string)$qNode->questiontext->text : (string)($qNode->questiontext ?? ""),
        'generalfeedback' => isset($qNode->generalfeedback->text) ? (string)$qNode->generalfeedback->text : (string)($qNode->generalfeedback ?? ""),
        'specificfeedback' => isset($qNode->specificfeedback->text) ? (string)$qNode->specificfeedback->text : (string)($qNode->specificfeedback ?? ""),
        'questionnote' => isset($qNode->questionnote->text) ? (string)$qNode->questionnote->text : (string)($qNode->questionnote ?? ""),
    ];

    foreach ($ctFields as $fName => $fText) {
        if (trim($fText) === '') continue;
        try {
            $ct = \castext2_evaluatable::make_from_source($fText, $fName);
            if (!$ct->get_valid()) {
                $errs = $ct->get_errors(false);
                if (is_array($errs)) {
                    foreach ($errs as $err) {
                        $addError($fName, (string)$err);
                    }
                } else if (!empty($errs)) {
                    $addError($fName, (string)$errs);
                }
            }
        } catch (\Throwable $e) {
            $addError($fName, $e->getMessage());
        }
    }

    return $probedErrors;
}

function macstack_handle_vars(array $data) {
    $xml = $data["questionDefinition"] ?? "";
    if (empty($xml)) {
        http_response_code(400);
        echo json_encode(["errors" => "Missing questionDefinition"]);
        exit(0);
    }

    $seed = isset($data["seed"]) && $data["seed"] !== null ? (int)$data["seed"] : null;
    $probedErrors = [];

    try {
        $loaded = StackQuestionLoader::loadxml($xml);
        /** @var \qtype_stack_question $question */
        $question = $loaded["question"];

        if ($seed !== null) {
            $question->seed = $seed;
        } else if (!empty($question->deployedseeds)) {
            $question->seed = (int)$question->deployedseeds[0];
        } else {
            $question->seed = 1;
        }

        $question->initialise_question_from_seed();

        $errors = !empty($question->runtimeerrors) ? implode("\n", array_keys($question->runtimeerrors)) : "";
        $note = $question->get_question_summary();

        // Extract variables using stack_cas_keyval
        $variables = [];
        $qvarsRaw = $question->questionvariables ?? "";
        try {
            $kv = new \stack_cas_keyval($qvarsRaw, $question->options, $question->seed, 'questionvariables');
            $isValid = $kv->get_valid();
            if (!$isValid) {
                $errList = $kv->get_errors(false, 'strings');
                $errStr = implode("\n", $errList);
                if (empty($errors)) {
                    $errors = $errStr;
                }
                // Partial variable evaluation: if syntax error has line number, try prefix
                if (preg_match('/\(At about line\s+(\d+)/i', $errStr, $mLine)) {
                    $errLine = (int)$mLine[1];
                    if ($errLine > 1) {
                        $qvarsLines = explode("\n", $qvarsRaw);
                        $prefixLines = array_slice($qvarsLines, 0, $errLine - 1);
                        $prefixRaw = implode("\n", $prefixLines);
                        if (trim($prefixRaw) !== '') {
                            try {
                                $prefixKv = new \stack_cas_keyval($prefixRaw, $question->options, $question->seed);
                                if ($prefixKv->get_valid()) {
                                    $pSession = $prefixKv->get_session();
                                    $pSession->instantiate();
                                    foreach ($pSession->get_session() as $stmt) {
                                        if ($stmt instanceof \stack_ast_container) {
                                            try {
                                                if ($stmt->is_correctly_evaluated()) {
                                                    $variables[] = [
                                                        "name" => $stmt->get_key(),
                                                        "expr" => $stmt->get_inputform(true),
                                                        "value" => $stmt->get_value(),
                                                        "display" => $stmt->get_display()
                                                    ];
                                                }
                                            } catch (\Throwable $eStmt) {}
                                        }
                                    }
                                }
                            } catch (\Throwable $ePrefix) {}
                        }
                    }
                }
            } else {
                $session = $kv->get_session();
                $session->instantiate();
                foreach ($session->get_session() as $stmt) {
                    if ($stmt instanceof \stack_ast_container) {
                        try {
                            if ($stmt->is_correctly_evaluated()) {
                                $variables[] = [
                                    "name" => $stmt->get_key(),
                                    "expr" => $stmt->get_inputform(true),
                                    "value" => $stmt->get_value(),
                                    "display" => $stmt->get_display()
                                ];
                            }
                        } catch (\Throwable $eStmt) {}
                    }
                }
            }
        } catch (\Throwable $e) {
            if (empty($errors)) {
                $errors = "Error evaluating variables: " . $e->getMessage();
            }
        }

        // If errors exist, probe xml for full diagnostics
        if (!empty($errors)) {
            $probedErrors = macstack_probe_xml_cas_errors($xml, $question->options ?? null, $question->seed);
        }

        // Extract inputs
        $inputs = [];
        foreach ($question->inputs as $name => $input) {
            try {
                $tavalue = $question->get_ta_for_input($name);
                $state = $question->get_input_state($name, []);
                $render = $input->render($state, "ans_" . $name, false, $tavalue);
                $inputs[$name] = [
                    "tans" => $input->get_teacher_answer(),
                    "value" => $tavalue,
                    "api_solution" => $input->get_api_solution($tavalue),
                    "render" => $render
                ];
            } catch (\Throwable $eInp) {}
        }

        echo json_encode([
            "seed" => $question->seed,
            "questionnote" => $note,
            "variables" => $variables,
            "inputs" => $inputs,
            "errors" => $errors,
            "probed_errors" => $probedErrors
        ]);
        exit(0);

    } catch (\Throwable $e) {
        $effSeed = $seed ?? 1;
        $probedErrors = macstack_probe_xml_cas_errors($xml, null, $effSeed);

        // Attempt to evaluate questionvariables even when loadxml failed
        $fallbackVars = [];
        try {
            libxml_use_internal_errors(true);
            $sxe = simplexml_load_string($xml);
            if ($sxe !== false) {
                $qNode = ($sxe->getName() === 'question' && (string)$sxe['type'] === 'stack')
                    ? $sxe
                    : ($sxe->xpath("//question[@type='stack']")[0] ?? null);
                if ($qNode) {
                    $rawQvars = isset($qNode->questionvariables->text)
                        ? (string)$qNode->questionvariables->text
                        : (string)($qNode->questionvariables ?? "");
                    if (trim($rawQvars) !== '') {
                        $kv = new \stack_cas_keyval($rawQvars, null, $effSeed, 'questionvariables');
                        if ($kv->get_valid()) {
                            $sess = $kv->get_session();
                            $sess->instantiate();
                            foreach ($sess->get_session() as $stmt) {
                                if ($stmt instanceof \stack_ast_container) {
                                    try {
                                        if ($stmt->is_correctly_evaluated()) {
                                            $fallbackVars[] = [
                                                "name" => $stmt->get_key(),
                                                "expr" => $stmt->get_inputform(true),
                                                "value" => $stmt->get_value(),
                                                "display" => $stmt->get_display()
                                            ];
                                        }
                                    } catch (\Throwable $eStmt) {}
                                }
                            }
                        }
                    }
                }
            }
        } catch (\Throwable $eFallback) {}

        echo json_encode([
            "seed" => $effSeed,
            "questionnote" => "",
            "variables" => $fallbackVars,
            "inputs" => (object)[],
            "errors" => $e->getMessage(),
            "probed_errors" => $probedErrors
        ]);
        exit(0);
    }
}

function macstack_handle_seeds(array $data) {
    $xml = $data["questionDefinition"] ?? "";
    if (empty($xml)) {
        http_response_code(400);
        echo json_encode(["error" => "Missing questionDefinition"]);
        exit(0);
    }

    $targetCount = isset($data["count"]) ? (int)$data["count"] : 50;
    $maxAttempts = isset($data["max_attempts"]) ? (int)$data["max_attempts"] : 250;
    $inputSeeds = isset($data["seeds"]) && is_array($data["seeds"]) ? $data["seeds"] : [];

    $seenNotes = [];
    $collectedSeeds = [];
    $variants = [];
    $attempts = 0;
    $firstError = "";

    // First evaluate provided existing/input seeds
    foreach ($inputSeeds as $s) {
        $s = (int)$s;
        $attempts++;
        try {
            $loaded = StackQuestionLoader::loadxml($xml);
            /** @var \qtype_stack_question $question */
            $question = $loaded["question"];
            $question->seed = $s;
            $question->initialise_question_from_seed();
            if (empty($question->runtimeerrors)) {
                $note = $question->get_question_summary();
                if (!isset($seenNotes[$note])) {
                    $seenNotes[$note] = true;
                    $collectedSeeds[] = $s;
                    $variants[] = [
                        "seed" => $s,
                        "questionnote" => $note
                    ];
                }
            } else {
                if (empty($firstError)) {
                    $firstError = implode("\n", array_keys($question->runtimeerrors));
                }
            }
        } catch (\Throwable $e) {
            if (empty($firstError)) {
                $firstError = $e->getMessage();
            }
        }
        if (count($collectedSeeds) >= $targetCount) {
            break;
        }
    }

    // Now generate candidate seeds if more needed
    $candidate = 1;
    while (count($collectedSeeds) < $targetCount && $attempts < $maxAttempts) {
        $attempts++;
        $s = $candidate++;
        if (in_array($s, $collectedSeeds, true)) {
            continue;
        }
        try {
            $loaded = StackQuestionLoader::loadxml($xml);
            /** @var \qtype_stack_question $question */
            $question = $loaded["question"];
            $question->seed = $s;
            $question->initialise_question_from_seed();
            if (empty($question->runtimeerrors)) {
                $note = $question->get_question_summary();
                if (!isset($seenNotes[$note])) {
                    $seenNotes[$note] = true;
                    $collectedSeeds[] = $s;
                    $variants[] = [
                        "seed" => $s,
                        "questionnote" => $note
                    ];
                }
            } else {
                if (empty($firstError)) {
                    $firstError = implode("\n", array_keys($question->runtimeerrors));
                }
            }
        } catch (\Throwable $e) {
            if (empty($firstError)) {
                $firstError = $e->getMessage();
            }
        }
    }

    $probedErrors = [];
    if (count($collectedSeeds) === 0) {
        $probedErrors = macstack_probe_xml_cas_errors($xml, null, 1);
    }

    echo json_encode([
        "seeds" => $collectedSeeds,
        "variants" => $variants,
        "count" => count($collectedSeeds),
        "attempts" => $attempts,
        "first_error" => $firstError,
        "probed_errors" => $probedErrors
    ]);
    exit(0);
}

function macstack_standard_prt_feedback(\qtype_stack_question $question, \prt_evaluatable $result, $feedbackstyle) {
    $class = '';
    if ($result->get_score() < 0.000001) {
        $class = 'incorrect';
    } else if ($result->get_score() > 0.999999) {
        $class = 'correct';
    } else {
        $class = 'partiallycorrect';
    }

    $field = 'prt' . $class . 'instantiated';

    if ($feedbackstyle === 2 || $feedbackstyle === 3) {
        $s = get_string('symbolicprt' . $class . 'feedback', 'qtype_stack');
        return \html_writer::tag('span', $s, ['class' => $class]);
    }

    if ($question->$field) {
        return \html_writer::tag('div',
            \stack_maths::process_display_castext(
                $question->$field->apply_placeholder_holder($question->$field->get_rendered($question->castextprocessor))
            ),
            ['class' => $class]
        );
    }

    return '';
}

function macstack_handle_grade(array $data) {
    $xml = $data["questionDefinition"] ?? "";
    if (empty($xml)) {
        http_response_code(400);
        echo json_encode(["error" => "Missing questionDefinition"]);
        exit(0);
    }

    $seed = isset($data["seed"]) && $data["seed"] !== null ? (int)$data["seed"] : null;

    try {
        $loaded = StackQuestionLoader::loadxml($xml);
        /** @var \qtype_stack_question $question */
        $question = $loaded["question"];

        StackSeedHelper::initialize_seed($question, $seed);
        $question->initialise_question_from_seed();

        $question->castextprocessor = new \castext2_qa_processor(new \stack_outofcontext_process());

        if (!empty($question->runtimeerrors)) {
            echo json_encode([
                "isgradable" => false,
                "has_prt_errors" => false,
                "has_cas_error" => true,
                "error" => implode("\n", array_keys($question->runtimeerrors)),
                "probed_errors" => macstack_probe_xml_cas_errors($xml, $question->options ?? null, $question->seed ?? 1),
            ]);
            exit(0);
        }

        $translate = new \stack_multilang();
        $translate->search = '/(<span(\s+lang="[a-zA-Z0-9_-]+"|\s+class="multilang")' .
                             '{2}\s*>.*?<\/span>)(\s*<span(\s+lang="[a-zA-Z0-9_-]+"' .
                             '|\s+class="multilang"){2}\s*>.*?<\/span>)+/is';
        $language = current_language();

        $answers = $data['answers'] ?? [];
        if (!is_array($answers)) {
            $answers = [];
        }

        foreach ($question->inputs as $name => $input) {
            if ($input->get_extra_option('allowempty') && !array_key_exists($name, $answers)) {
                $answers[$name] = '';
            }
            if (method_exists($input, 'maxima_to_response_array') && isset($answers[$name]) && !isset($answers[$name . '_sub_0_0'])) {
                try {
                    $expanded = $input->maxima_to_response_array($answers[$name]);
                    if (is_array($expanded)) {
                        $answers = array_merge($answers, $expanded);
                    }
                } catch (\Throwable $e) {
                    // Ignore, let STACK handle
                }
            }
        }

        $plots = [];
        $storeprefix = uniqid();
        $scores = [];
        $prts = [];
        $prtresults = [];
        $anyGradablePrt = false;
        $hasPrtErrors = false;

        foreach ($question->prts as $index => $prt) {
            $hasInputs = $question->has_necessary_prt_inputs($prt, $answers, true);
            if (!$hasInputs) {
                continue;
            }
            $anyGradablePrt = true;

            $result = null;
            $prtErrList = [];
            try {
                $result = $question->get_prt_result($index, $answers, true);
                if ($result) {
                    $rawErrs = $result->get_errors();
                    if (!empty($rawErrs)) {
                        $prtErrList = array_merge($prtErrList, is_array($rawErrs) ? $rawErrs : [$rawErrs]);
                    }
                    if (method_exists($result, 'get_fverrors')) {
                        $fvErrs = $result->get_fverrors();
                        if (!empty($fvErrs)) {
                            $prtErrList = array_merge($prtErrList, is_array($fvErrs) ? $fvErrs : [$fvErrs]);
                        }
                    }
                }
            } catch (\Throwable $prtExc) {
                $prtErrList = [$prtExc->getMessage()];
            }

            $cleanNotes = [];
            if ($result) {
                $rawNotes = $result->get_answernotes();
                if (is_array($rawNotes)) {
                    foreach ($rawNotes as $n) {
                        if ($n !== null && trim((string)$n) !== '') {
                            $cleanNotes[] = trim((string)$n);
                        }
                    }
                }
            }

            $cleanTrace = [];
            if ($result) {
                $rawTrace = $result->get_trace();
                if (is_array($rawTrace)) {
                    foreach ($rawTrace as $t) {
                        if ($t !== null && trim((string)$t) !== '') {
                            $cleanTrace[] = trim((string)$t);
                        }
                    }
                }
            }

            if (!empty($prtErrList)) {
                $hasPrtErrors = true;
                $scores[$index] = null;
                $prts[$index] = "";
                $prtresults[$index] = [
                    "name" => $index,
                    "has_errors" => true,
                    "score" => null,
                    "penalty" => null,
                    "answernotes" => $cleanNotes,
                    "trace" => $cleanTrace,
                    "errors" => is_array($prtErrList) ? implode("\n", $prtErrList) : (string)$prtErrList,
                ];
                continue;
            }

            try {
                $feedbackstyle = $prt->get_feedbackstyle();
                $feedback = $result->apply_placeholder_holder($result->get_feedback());
                $standardfeedback = macstack_standard_prt_feedback($question, $result, $feedbackstyle);

                switch ($feedbackstyle) {
                    case 0:
                        $overallfeedback = $feedback;
                        break;
                    case 1:
                    case 2:
                        $overallfeedback = $standardfeedback . $feedback;
                        break;
                    case 3:
                        $overallfeedback = $standardfeedback;
                        break;
                    default:
                        $overallfeedback = "Invalid Feedback style";
                        break;
                }

                $scores[$index] = $result->get_score();
                $prts[$index] = $translate->filter(
                    \stack_maths::process_display_castext($overallfeedback),
                    $language
                );
                StackPlotReplacer::replace_plots($plots, $prts[$index], "prt-" . $index, $storeprefix);

                $prtresults[$index] = [
                    "name" => $index,
                    "score" => $result->get_score(),
                    "penalty" => $result->get_penalty(),
                    "answernotes" => $cleanNotes,
                    "trace" => $cleanTrace,
                    "errors" => ""
                ];
            } catch (\Throwable $fbExc) {
                $hasPrtErrors = true;
                $scores[$index] = null;
                $prts[$index] = "";
                $prtresults[$index] = [
                    "name" => $index,
                    "has_errors" => true,
                    "score" => null,
                    "penalty" => null,
                    "answernotes" => $cleanNotes,
                    "trace" => $cleanTrace,
                    "errors" => $fbExc->getMessage(),
                ];
            }
        }

        if (!$anyGradablePrt && !empty($question->prts)) {
            echo json_encode([
                "isgradable" => false,
                "has_prt_errors" => false,
                "has_cas_error" => false,
                "score" => null,
                "scores" => null,
                "scoreweights" => null,
                "specificfeedback" => null,
                "prts" => null,
                "prtresults" => null,
                "gradingassets" => null,
                "responsesummary" => null,
                "iframes" => null
            ]);
            exit(0);
        }

        $weights = $question->get_parts_and_weights();
        if ($hasPrtErrors) {
            $scores['total'] = null;
        } else {
            $scores['total'] = 0;
            foreach ($weights as $prtKey => $weight) {
                $prtscore = $weights[$prtKey] * ($scores[$prtKey] ?? 0);
                $scores['total'] += $prtscore;
            }
        }
        $weights['total'] = $question->defaultmark;

        $specificfeedback = "";
        try {
            if (isset($question->specificfeedbackinstantiated) && $question->specificfeedbackinstantiated) {
                $specificfeedback = $translate->filter(
                    $question->specificfeedbackinstantiated->apply_placeholder_holder(
                        $question->specificfeedbackinstantiated->get_rendered($question->castextprocessor)
                    ),
                    $language
                );
                StackPlotReplacer::replace_plots($plots, $specificfeedback, "specificfeedback", $storeprefix);
            }
        } catch (\Throwable $sfExc) {
            $hasPrtErrors = true;
            $specificfeedback = "";
        }

        echo json_encode([
            "isgradable" => true,
            "has_prt_errors" => $hasPrtErrors,
            "has_cas_error" => false,
            "score" => $scores['total'],
            "scores" => $scores,
            "scoreweights" => $weights,
            "specificfeedback" => $specificfeedback,
            "prts" => $prts,
            "prtresults" => $prtresults,
            "gradingassets" => (object)$plots,
            "responsesummary" => $question->summarise_response($answers),
            "iframes" => StackIframeHolder::$iframes
        ]);
        exit(0);

    } catch (\Throwable $e) {
        echo json_encode([
            "isgradable" => false,
            "has_prt_errors" => false,
            "has_cas_error" => true,
            "error" => $e->getMessage(),
            "probed_errors" => macstack_probe_xml_cas_errors($xml, null, $seed ?? 1),
        ]);
        exit(0);
    }
}
