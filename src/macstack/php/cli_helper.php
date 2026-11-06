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

function macstack_handle_vars(array $data) {
    $xml = $data["questionDefinition"] ?? "";
    if (empty($xml)) {
        http_response_code(400);
        echo json_encode(["errors" => "Missing questionDefinition"]);
        exit(0);
    }

    try {
        $loaded = StackQuestionLoader::loadxml($xml);
        /** @var \qtype_stack_question $question */
        $question = $loaded["question"];

        $seed = isset($data["seed"]) && $data["seed"] !== null ? (int)$data["seed"] : null;
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
        try {
            $kv = new \stack_cas_keyval($question->questionvariables, $question->options, $question->seed);
            $kv->get_valid();
            $session = $kv->get_session();
            $session->instantiate();
            foreach ($session->get_session() as $stmt) {
                if ($stmt instanceof \stack_ast_container) {
                    $variables[] = [
                        "name" => $stmt->get_key(),
                        "expr" => $stmt->get_inputform(true),
                        "value" => $stmt->get_value(),
                        "display" => $stmt->get_display()
                    ];
                }
            }
        } catch (\Throwable $e) {
            if (empty($errors)) {
                $errors = "Error evaluating variables: " . $e->getMessage();
            }
        }

        // Extract inputs
        $inputs = [];
        foreach ($question->inputs as $name => $input) {
            $tavalue = $question->get_ta_for_input($name);
            $state = $question->get_input_state($name, []);
            $render = $input->render($state, "ans_" . $name, false, $tavalue);
            $inputs[$name] = [
                "tans" => $input->get_teacher_answer(),
                "value" => $tavalue,
                "api_solution" => $input->get_api_solution($tavalue),
                "render" => $render
            ];
        }

        echo json_encode([
            "seed" => $question->seed,
            "questionnote" => $note,
            "variables" => $variables,
            "inputs" => $inputs,
            "errors" => $errors
        ]);
        exit(0);

    } catch (\Throwable $e) {
        echo json_encode([
            "seed" => $data["seed"] ?? null,
            "questionnote" => "",
            "variables" => [],
            "inputs" => (object)[],
            "errors" => $e->getMessage()
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
            }
        } catch (\Throwable $e) {
            // Skip invalid seeds
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
            }
        } catch (\Throwable $e) {
            // Skip
        }
    }

    echo json_encode([
        "seeds" => $collectedSeeds,
        "variants" => $variants,
        "count" => count($collectedSeeds),
        "attempts" => $attempts
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

    try {
        $loaded = StackQuestionLoader::loadxml($xml);
        /** @var \qtype_stack_question $question */
        $question = $loaded["question"];

        $seed = isset($data["seed"]) && $data["seed"] !== null ? (int)$data["seed"] : null;
        StackSeedHelper::initialize_seed($question, $seed);
        $question->initialise_question_from_seed();

        $question->castextprocessor = new \castext2_qa_processor(new \stack_outofcontext_process());

        if (!empty($question->runtimeerrors)) {
            http_response_code(500);
            echo json_encode(["error" => implode("\n", array_keys($question->runtimeerrors))]);
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
        }

        $plots = [];
        $storeprefix = uniqid();
        $scores = [];
        $prts = [];
        $prtresults = [];

        foreach ($question->prts as $index => $prt) {
            $result = $question->get_prt_result($index, $answers, true);

            if ($result->get_errors() || !$question->has_necessary_prt_inputs($prt, $answers, true)) {
                echo json_encode([
                    "isgradable" => false,
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

            $rawNotes = $result->get_answernotes();
            $cleanNotes = [];
            if (is_array($rawNotes)) {
                foreach ($rawNotes as $n) {
                    if ($n !== null && trim($n) !== '') {
                        $cleanNotes[] = trim($n);
                    }
                }
            }

            $rawTrace = $result->get_trace();
            $cleanTrace = [];
            if (is_array($rawTrace)) {
                foreach ($rawTrace as $t) {
                    if ($t !== null && trim($t) !== '') {
                        $cleanTrace[] = trim($t);
                    }
                }
            }

            $prtresults[$index] = [
                "name" => $index,
                "score" => $result->get_score(),
                "penalty" => $result->get_penalty(),
                "answernotes" => $cleanNotes,
                "trace" => $cleanTrace,
                "errors" => implode("\n", $result->get_errors())
            ];
        }

        $weights = $question->get_parts_and_weights();
        $scores['total'] = 0;
        foreach ($weights as $prt => $weight) {
            $prtscore = $weights[$prt] * $scores[$prt];
            $scores['total'] += $prtscore;
        }
        $weights['total'] = $question->defaultmark;

        $specificfeedback = $translate->filter(
            $question->specificfeedbackinstantiated->apply_placeholder_holder(
                $question->specificfeedbackinstantiated->get_rendered($question->castextprocessor)
            ),
            $language
        );
        StackPlotReplacer::replace_plots($plots, $specificfeedback, "specificfeedback", $storeprefix);

        echo json_encode([
            "isgradable" => true,
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
        http_response_code(500);
        echo json_encode([
            "error" => $e->getMessage(),
            "isgradable" => false
        ]);
        exit(0);
    }
}
