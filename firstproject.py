import tkinter as tk
import subprocess
from tkinter import filedialog
import threading
import ctypes
import chess
import chess.engine
import os
import json
import keyboard 

CONFIG_FILE = "chess_overlay_config.json"
DEFAULT_CONFIG = {
    "engine_path": "",
    "square_size": 60,
    "elo": 1500,
    "depth": 10,
}

PIECES = {
    'P': '♙', 'N': '♘', 'B': '♗', 'R': '♖', 'Q': '♕', 'K': '♔',
    'p': '♟', 'n': '♞', 'b': '♝', 'r': '♜', 'q': '♛', 'k': '♚'
}

class ChessOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.8) 

        self.config = self.load_config()
        self.SQUARE_SIZE = self.config["square_size"]
        self.ELO = self.config["elo"]
        self.DEPTH = self.config["depth"]
        self.max_elo = 3200 
        
        self.board = chess.Board()
        self.selected_square = None
        self.pending_promotion = None 
        self.best_promo_piece = None
        self.engine = None
        self.engine_loaded = False
        self.click_through = False  
        self.flipped = False  

        self.canvas = tk.Canvas(self.root, bg="#111111", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_click)
        
        keyboard.add_hotkey('f8', self.toggle_click_through)
        self.root.bind("f", lambda e: self.toggle_flip()) 
        self.root.bind("<Control-z>", lambda e: self.undo_move())
        self.root.bind("<Control-r>", lambda e: self.reset_board())
        self.root.bind("=", lambda e: self.change_size(5))  
        self.root.bind("-", lambda e: self.change_size(-5)) 
        self.root.bind("]", lambda e: self.change_elo(100))
        self.root.bind("[", lambda e: self.change_elo(-100))
        self.root.bind("0", lambda e: self.change_depth())
        self.root.bind("<Escape>", lambda e: self.quit())

        self.rebuild_ui()
        self._init_engine()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return {**DEFAULT_CONFIG, **json.load(f)}
            except: return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def rebuild_ui(self):
        self.BOARD_SIZE = self.SQUARE_SIZE * 8
        self.TITLE_HEIGHT = 25
        self.INFO_HEIGHT = 100 
        self.canvas.config(width=self.BOARD_SIZE, height=self.TITLE_HEIGHT + self.BOARD_SIZE + self.INFO_HEIGHT)
        self.refresh_ui()

    def change_size(self, delta):
        self.SQUARE_SIZE = max(30, min(120, self.SQUARE_SIZE + delta))
        self.rebuild_ui()

    def refresh_ui(self):
        self.canvas.delete("all")
        offset = self.TITLE_HEIGHT
        self.canvas.create_rectangle(0, 0, self.BOARD_SIZE, offset, fill="#222222")
        title = self.canvas.create_text(self.BOARD_SIZE//2, offset//2, text="::: DRAG :::", fill="#888888", font=("Arial", 7, "bold"))
        self.canvas.tag_bind(title, "<ButtonPress-1>", self._start_drag)
        self.canvas.tag_bind(title, "<B1-Motion>", self._do_drag)
        
        for r in range(8):
            for c in range(8):
                x1, y1 = c * self.SQUARE_SIZE, r * self.SQUARE_SIZE + offset
                x2, y2 = x1 + self.SQUARE_SIZE, y1 + self.SQUARE_SIZE
                color = "#1a1a1a" if (r+c)%2==0 else "#111111"
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="#222222", tags="grid")

        if self.selected_square is not None:
            tx, ty = self.get_sq_center(self.selected_square)
            self.canvas.create_rectangle(tx-self.SQUARE_SIZE//2, ty-self.SQUARE_SIZE//2, tx+self.SQUARE_SIZE//2, ty+self.SQUARE_SIZE//2, outline="#00ffff", width=2)

        for sq in chess.SQUARES:
            x, y = self.get_sq_center(sq)
            p = self.board.piece_at(sq)
            if p:
                p_color = "#ffffff" if p.color == chess.WHITE else "#ffaa00"
                self.canvas.create_text(x, y, text=PIECES.get(p.symbol()), fill=p_color, font=("Arial", int(self.SQUARE_SIZE*0.6), "bold"))
        
        info_y = offset + self.BOARD_SIZE
        self.canvas.create_text(10, info_y + 15, anchor="w", text=f"ELO: {self.ELO} (MAX: {self.max_elo}) | DEPTH: {self.DEPTH}", fill="#ffcc00", font=("Consolas", 9, "bold"))
        self.eval_text_id = self.canvas.create_text(10, info_y + 35, anchor="w", text="Eval: 0.0", fill="white", font=("Consolas", 9))
        self.move_text_id = self.canvas.create_text(10, info_y + 55, anchor="w", text="Best: -", fill="#00aaff", font=("Consolas", 10, "bold"))
        
        if self.pending_promotion: self.draw_promotion_menu()
        else: self.force_analysis()

    def draw_promotion_menu(self):
        offset, menu_w, menu_h = self.TITLE_HEIGHT, self.SQUARE_SIZE * 4, self.SQUARE_SIZE
        x1, y1 = (self.BOARD_SIZE - menu_w) // 2, offset + (self.BOARD_SIZE - menu_h) // 2
        self.canvas.create_rectangle(x1-10, y1-30, x1+menu_w+10, y1+menu_h+10, fill="#1a1a1a", outline="#555555", width=2)
        self.canvas.create_text(self.BOARD_SIZE//2, y1-15, text="CHOOSE PROMOTION", fill="#00ff00", font=("Arial", 8, "bold"))
        promo_pieces = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
        symbols = ['Q', 'R', 'B', 'N'] if self.board.turn == chess.WHITE else ['q', 'r', 'b', 'n']
        for i, p_type in enumerate(promo_pieces):
            px1 = x1 + i * self.SQUARE_SIZE
            is_best = (p_type == self.best_promo_piece)
            rect = self.canvas.create_rectangle(px1, y1, px1 + self.SQUARE_SIZE, y1 + self.SQUARE_SIZE, fill=("#004400" if is_best else "#222222"), outline=("#00ff00" if is_best else "#444444"))
            txt = self.canvas.create_text(px1 + self.SQUARE_SIZE//2, y1 + self.SQUARE_SIZE//2, text=PIECES.get(symbols[i]), fill="white", font=("Arial", int(self.SQUARE_SIZE*0.5)))
            for item in [rect, txt]: self.canvas.tag_bind(item, "<Button-1>", lambda e, pt=p_type: self.complete_promotion(pt))

    def on_click(self, event):
        if self.click_through or self.pending_promotion: return
        if event.y < self.TITLE_HEIGHT or event.y > (self.TITLE_HEIGHT + self.BOARD_SIZE): return
        col, row = event.x // self.SQUARE_SIZE, (event.y - self.TITLE_HEIGHT) // self.SQUARE_SIZE
        sq = chess.square(7-col, row) if self.flipped else chess.square(col, 7-row)
        p = self.board.piece_at(sq)
        if self.selected_square is None:
            if p and p.color == self.board.turn: self.selected_square = sq
        else:
            from_sq, to_sq = self.selected_square, sq
            piece = self.board.piece_at(from_sq)
            if piece and piece.piece_type == chess.PAWN and chess.square_rank(to_sq) in [0, 7]:
                if chess.Move(from_sq, to_sq, promotion=chess.QUEEN) in self.board.legal_moves:
                    self.pending_promotion = (from_sq, to_sq)
                    threading.Thread(target=self._analyze_promotion_thread, daemon=True).start()
                    self.refresh_ui(); return
            move = chess.Move(from_sq, to_sq)
            if move in self.board.legal_moves: self.board.push(move); self.selected_square = None
            else: self.selected_square = sq if p and p.color == self.board.turn else None
        self.refresh_ui()

    def _analyze_promotion_thread(self):
        if not self.engine_loaded or not self.pending_promotion: return
        best_score, best_p, from_sq, to_sq = -99999, chess.QUEEN, self.pending_promotion[0], self.pending_promotion[1]
        for p_type in [chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP]:
            self.board.push(chess.Move(from_sq, to_sq, promotion=p_type))
            info = self.engine.analyse(self.board, chess.engine.Limit(time=0.1))
            self.board.pop()
            score = info["score"].relative.score() if info["score"].relative.score() is not None else 0
            if score > best_score: best_score, best_p = score, p_type
        self.best_promo_piece = best_p
        self.root.after(0, self.refresh_ui)

    def complete_promotion(self, piece_type):
        from_sq, to_sq = self.pending_promotion
        self.board.push(chess.Move(from_sq, to_sq, promotion=piece_type))
        self.pending_promotion = self.best_promo_piece = self.selected_square = None
        self.refresh_ui()

    def _init_engine(self):
        if self.config["engine_path"] and os.path.exists(self.config["engine_path"]):
            threading.Thread(target=self._load_engine_thread, daemon=True).start()
        else: self.prompt_engine_path()

    def _load_engine_thread(self):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.engine = chess.engine.SimpleEngine.popen_uci(self.config["engine_path"], startupinfo=si)
       
        if "UCI_Elo" in self.engine.options:
            self.max_elo = self.engine.options["UCI_Elo"].max
            self.ELO = min(self.ELO, self.max_elo)
        self.engine_loaded = True
        self._update_engine_params()

    def _update_engine_params(self):
        if self.engine_loaded:
            try:
                self.engine.configure({"UCI_LimitStrength": True, "UCI_Elo": self.ELO})
                self.force_analysis()
            except: pass

    def change_elo(self, delta):
        self.ELO = max(100, min(self.max_elo, self.ELO + delta))
        self._update_engine_params(); self.refresh_ui()

    def change_depth(self):
        depths = [5, 10, 15, 20]
        self.DEPTH = depths[(depths.index(self.DEPTH) + 1) % len(depths)] if self.DEPTH in depths else 10
        self.refresh_ui()

    def get_sq_center(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        d_col, d_row = (7-f if self.flipped else f), (r if self.flipped else 7-r)
        return d_col * self.SQUARE_SIZE + self.SQUARE_SIZE // 2, d_row * self.SQUARE_SIZE + self.SQUARE_SIZE // 2 + self.TITLE_HEIGHT

    def _analyze_thread(self):
        if self.board.is_game_over() or self.pending_promotion: return
        try:
            info = self.engine.analyse(self.board, chess.engine.Limit(depth=self.DEPTH))
            best_move = info.get("pv", [None])[0]
            score = info["score"].relative.score()/100.0 if "score" in info and info["score"].relative.score() is not None else 0
            self.root.after(0, lambda: self._update_analysis_ui(best_move, score))
        except: pass

    def _update_analysis_ui(self, move, score):
        try:
            self.canvas.itemconfig(self.eval_text_id, text=f"Eval: {score:+.2f}")
            if move:
                self.canvas.itemconfig(self.move_text_id, text=f"Best Move: {move}")
                x1, y1 = self.get_sq_center(move.from_square)
                x2, y2 = self.get_sq_center(move.to_square)
                self.canvas.create_line(x1, y1, x2, y2, fill="#00ff00", width=3, arrow=tk.LAST, tags="hl")
        except: pass

    def toggle_click_through(self):
        self.click_through = not self.click_through
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, (style | 0x80000 | 0x20) if self.click_through else (style & ~0x20))
        self.root.attributes("-alpha", 0.3 if self.click_through else 0.8); self.refresh_ui()

    def force_analysis(self):
        if self.engine_loaded: threading.Thread(target=self._analyze_thread, daemon=True).start()

    def _start_drag(self, e):
        self._start_x, self._start_y, self._win_x, self._win_y = e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y()

    def _do_drag(self, e):
        self.root.geometry(f"+{self._win_x + (e.x_root - self._start_x)}+{self._win_y + (e.y_root - self._start_y)}")

    def undo_move(self):
        if self.board.move_stack: self.board.pop(); self.selected_square = None; self.refresh_ui()
    def reset_board(self):
        self.board = chess.Board(); self.selected_square = None; self.refresh_ui()
    def prompt_engine_path(self):
        path = filedialog.askopenfilename()
        if path: self.config["engine_path"] = path; json.dump(self.config, open(CONFIG_FILE, 'w')); self._init_engine()
    def quit(self):
        keyboard.unhook_all(); 
        if self.engine: self.engine.quit()
        self.root.destroy()

if __name__ == "__main__":
    ChessOverlay().root.mainloop()
