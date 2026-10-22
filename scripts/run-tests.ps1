param(
    [string]$Image = 'self-ci'
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $repo
try {
    python "$PSScriptRoot/check_architecture_docs.py"
    if ($LASTEXITCODE -ne 0) { throw "Architecture documentation check failed with exit code $LASTEXITCODE." }

    python "$PSScriptRoot/check_docs_claims.py"
    if ($LASTEXITCODE -ne 0) { throw "Documentation claims check failed with exit code $LASTEXITCODE." }

    docker build --tag $Image .
    if ($LASTEXITCODE -ne 0) { throw "Docker image build failed with exit code $LASTEXITCODE." }

    # Dockerfile supplies PYTHONPATH=/opt:/opt/agent for both suites.
    docker run --rm --entrypoint python `
        --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" `
        $Image -m unittest discover -s /opt/agent/tests -v
    if ($LASTEXITCODE -ne 0) { throw "Harness tests failed with exit code $LASTEXITCODE." }

    # Hidden eval definitions stay on the host and never enter the self image.
    docker run --rm --entrypoint python `
        --mount "type=bind,source=$repo/eval,target=/opt/eval,readonly" `
        --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" `
        $Image -m unittest discover -s /opt/eval/tests -v
    if ($LASTEXITCODE -ne 0) { throw "Eval tests failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
