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
require_once $qtypeStackDir . "/stack/cas/keyval.class.php";

use api\util\StackQuestionLoader;

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
