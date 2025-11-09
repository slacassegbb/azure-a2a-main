# Start All contoso Agents
# This script starts all contoso agents in separate PowerShell windows

Write-Host "Starting all contoso agents..." -ForegroundColor Green

$agents = @(
    @{Dir="contoso_agents\authentication_agent"; Args=""},
    @{Dir="contoso_agents\outage_check_agent"; Args=""},
    @{Dir="contoso_agents\modem_check_agent"; Args=""},
    @{Dir="contoso_agents\internet_plan_agent"; Args=""},
    @{Dir="contoso_agents\network_performance_agent"; Args=""},
    @{Dir="contoso_agents\technical_dispatch_agent"; Args="--enable-ui"}
)

foreach ($agent in $agents) {
    $agentName = Split-Path $agent.Dir -Leaf
    Write-Host "Starting $agentName..." -ForegroundColor Cyan
    
    if ($agent.Args) {
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", "cd '$($agent.Dir)'; Write-Host 'Running $agentName with args: $($agent.Args)' -ForegroundColor Yellow; uv run . $($agent.Args)"
    } else {
        Start-Process pwsh -ArgumentList "-NoExit", "-Command", "cd '$($agent.Dir)'; Write-Host 'Running $agentName...' -ForegroundColor Yellow; uv run ."
    }
    
    Start-Sleep -Milliseconds 500
}

Write-Host "`nAll agents started in separate windows!" -ForegroundColor Green
Write-Host "Technical Dispatch Agent UI will be available at http://localhost:8086" -ForegroundColor Yellow
Write-Host "Press any key to exit this window..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
