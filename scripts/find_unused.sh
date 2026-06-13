#!/bin/bash
# Quick wrapper script for finding unused code

echo "🔍 dblift Unused Code Finder"
echo "================================"

# Run the analysis
python dblift_package/scripts/find_unused_code.py "$@"

echo ""
echo "💡 Quick Actions:"
echo "  • Review the report above"
echo "  • Use 'Find Usages' in your IDE to double-check findings"
echo "  • Start with removing unused imports and variables"
echo "  • Save report: './find_unused.sh --output unused_report.txt'"
echo "  • JSON format: './find_unused.sh --format json'" 