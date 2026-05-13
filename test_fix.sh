#!/bin/bash

echo "Testing openpilot fix..."
echo "========================"
echo ""

cd /Users/yanning/Projects/openpilot/Code

# Run openpilot to generate snake game
echo "Running: openpilot run --once '帮我在/Users/yanning/Projects/openpilot/TestDemo-Snake中做一个贪吃蛇'"
openpilot run --once "帮我在/Users/yanning/Projects/openpilot/TestDemo-Snake中做一个贪吃蛇"

echo ""
echo "========================"
echo "Checking results..."
echo ""

# Check if snake.py was created
if [ -f "/Users/yanning/Projects/openpilot/TestDemo-Snake/snake.py" ]; then
    FILE_SIZE=$(wc -c < "/Users/yanning/Projects/openpilot/TestDemo-Snake/snake.py")
    LINE_COUNT=$(wc -l < "/Users/yanning/Projects/openpilot/TestDemo-Snake/snake.py")

    echo "✓ snake.py created"
    echo "  Size: $FILE_SIZE bytes"
    echo "  Lines: $LINE_COUNT"

    if [ "$FILE_SIZE" -gt 100 ]; then
        echo "✓ File has content (not empty)"
    else
        echo "✗ File is empty or too small"
    fi
else
    echo "✗ snake.py was not created"
fi

echo ""
echo "Checking logs..."
tail -5 /Users/yanning/Projects/openpilot/Code/logs/openpilot.jsonl | jq -r '.event_type + " - " + (.payload.tool // "N/A")'
