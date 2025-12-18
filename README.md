# s2-project
using stockfish and ui chess board , transparent and elo + dept option
Windows

Python 3.9+

Stockfish engine (Windows build)

Python libraries
pip install python-chess keyboard


keyboard requires Run as Administrator to capture global hotkeys.

Setup

Clone the repo

git clone https://github.com/yourname/chess-overlay
cd chess-overlay


Run the script

python main.py


On first launch, select your stockfish.exe
(Path will be saved in chess_overlay_config.json)
Global (works even when overlay is locked)
Key	Action
F8	Toggle Click-through (Lock / Unlock overlay)
Overlay Controls
Key	Action
Left Click	Select & move pieces
Right Click + Drag	Move overlay window
F	Flip board
Ctrl + Z	Undo move
Ctrl + R	Reset board
+ / -	Increase / decrease board size
[ / ]	Decrease / increase Engine Elo
0	Cycle Depth (5 → 10 → 15 → 20)
ESC	Quit

![Uploading Screenshot 2025-12-18 214420.png…]()
