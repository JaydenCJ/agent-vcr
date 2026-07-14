# vhs tape to re-record docs/assets demo as a GIF (https://github.com/charmbracelet/vhs)
# Usage: run from the repository root with the package installed:
#   vhs docs/assets/demo.tape
Output docs/assets/demo.gif

Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"
Set TypingSpeed 40ms

Type "python examples/record_replay_demo.py out"
Enter
Sleep 3s

Type "agent-vcr diff out/baseline.json out/v2.json"
Enter
Sleep 3s

Type "echo $?"
Enter
Sleep 2s
