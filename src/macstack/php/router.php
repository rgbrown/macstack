<?php
// router.php - Router for PHP built-in server in macstack

ini_set("max_execution_time", "300");
ini_set("memory_limit", "512M");
set_time_limit(300);

error_reporting(0);

// CORS headers
header("Access-Control-Allow-Origin: *");
header("Access-Control-Allow-Methods: GET, POST, OPTIONS");
header("Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With");

if ($_SERVER["REQUEST_METHOD"] === "OPTIONS") {
    http_response_code(200);
    exit(0);
}

$uri = parse_url($_SERVER["REQUEST_URI"], PHP_URL_PATH);

// 1. Check custom macstack endpoints
if ($uri === "/macstack/health" || $uri === "/macstack/vars" || $uri === "/macstack/seeds" || $uri === "/grade") {
    require_once __DIR__ . "/cli_helper.php";
    macstack_handle_request($uri);
    exit(0);
}

// 2. Check plot requests
if (strpos($uri, "/plots/") === 0) {
    $runtimeDir = getenv("MACSTACK_RUNTIME_DIR") ?: (getenv("HOME") . "/.local/share/macstack");
    $filename = basename($uri);
    $plotFile = $runtimeDir . "/stack/plots/" . $filename;

    if (file_exists($plotFile) && is_file($plotFile)) {
        $ext = strtolower(pathinfo($plotFile, PATHINFO_EXTENSION));
        $contentTypes = [
            "svg" => "image/svg+xml",
            "png" => "image/png",
            "jpg" => "image/jpeg",
            "jpeg" => "image/jpeg",
            "gif" => "image/gif",
        ];
        $contentType = $contentTypes[$ext] ?? "application/octet-stream";
        header("Content-Type: " . $contentType);
        header("Content-Length: " . filesize($plotFile));
        header("Cache-Control: public, max-age=3600");
        readfile($plotFile);
        exit(0);
    } else {
        http_response_code(404);
        header("Content-Type: application/json");
        echo json_encode(["error" => "Plot file not found: $filename"]);
        exit(0);
    }
}

// 3. Serve static file from document root if it exists and isn't index.php
$docRoot = $_SERVER["DOCUMENT_ROOT"];
if ($uri !== "/" && !empty($docRoot) && file_exists($docRoot . $uri) && is_file($docRoot . $uri) && basename($uri) !== "index.php") {
    return false; // Let PHP built-in server handle static asset
}

// 4. Delegate all other routes to qtype_stack/api/public/index.php
$indexFile = $docRoot . "/index.php";
if (file_exists($indexFile)) {
    require $indexFile;
} else {
    http_response_code(404);
    header("Content-Type: application/json");
    echo json_encode(["error" => "API index.php not found at $indexFile"]);
}
