#!/bin/bash
# Master Test Runner for Backend Coverage
# Run this while backend is running with coverage

echo "🧪 Running All Backend Tests Against Live Backend"
echo "=================================================="
echo ""
echo "⚠️  Make sure backend is running with:"
echo "   cd backend && coverage run --source=hosts/multiagent backend_production.py"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."

cd "$(dirname "$0")/backend"

# Array of test files
tests=(
    "tests/test_workflow_execution.py"
    "tests/test_multiagent_flows.py"
    "tests/test_workflow_parallel_execution.py"
    "tests/test_workflow_parallel_image_analysis.py"
    "tests/test_image_generation_file_exchange.py"
    "tests/test_image_generation_analysis_flow.py"
    "tests/test_workflow_file_routing.py"
    "test_azure_agents.py"
    "test_hitl_full_workflow.py"
)

passed=0
failed=0
skipped=0

for test in "${tests[@]}"; do
    if [ -f "$test" ]; then
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "📝 Running: $test"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        if python "$test"; then
            ((passed++))
            echo "✅ PASSED: $test"
        else
            ((failed++))
            echo "❌ FAILED: $test"
        fi
    else
        ((skipped++))
        echo "⏭️  SKIPPED: $test (file not found)"
    fi
done

echo ""
echo "=================================================="
echo "📊 Test Summary"
echo "=================================================="
echo "✅ Passed:  $passed"
echo "❌ Failed:  $failed"
echo "⏭️  Skipped: $skipped"
echo ""
echo "💡 Next steps:"
echo "   1. Stop the backend (Ctrl+C in the backend terminal)"
echo "   2. Run: coverage report"
echo "   3. Run: coverage html"
echo "   4. Run: open htmlcov/index.html"
