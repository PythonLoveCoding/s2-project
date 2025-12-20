import tkinter as tk
from tkinter import filedialog
import threading
import ctypes
import chess
import chess.engine
import chess.polyglot
import os
import json
import math
import subprocess
import keyboard

CONFIG_FILE = "chess_overlay_config.json"
DEFAULT_CONFIG = {
    "engine_path": "c:\\Users\\admin\\Downloads\\stockfish-windows-x86-64-avx2\\stockfish\\stockfish-windows-x86-64-avx2.exe",
    "book_path": "C:\\Users\\admin\\Downloads\\identify chess board\\komodo.bin",
    "square_size": 60,
    "elo": 1500, #what ever u want can edit it tho
    "depth": 15 
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
        self.root.config(bg="#111111")

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
        self.book_reader = None
        self.engine_lock = threading.Lock()

        self.click_through = False
        self.flipped = False
        self.analyzing = False

        self.TITLE_HEIGHT = 25
        self.INFO_HEIGHT = 80
        self.BAR_WIDTH = 20

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
        self.root.bind("<Escape>", lambda e: self.quit())

        self.init_engine_system()
        self.rebuild_ui()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f)

    def init_engine_system(self):
        if self.config["engine_path"] and os.path.exists(self.config["engine_path"]):
            threading.Thread(target=self._start_engine_process, daemon=True).start()
        else:
            self.prompt_paths()

        if self.config["book_path"] and os.path.exists(self.config["book_path"]):
            try:
                self.book_reader = chess.polyglot.open_reader(self.config["book_path"])
            except:
                print("Không đọc được file Book")

    def _start_engine_process(self):
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.engine = chess.engine.SimpleEngine.popen_uci(
                self.config["engine_path"], startupinfo=si
            )

            if "UCI_Elo" in self.engine.options:
                self.max_elo = self.engine.options["UCI_Elo"].max
                self.ELO = min(self.ELO, self.max_elo)

            self.update_engine_options()
            self.trigger_analysis()
        except Exception as e:
            print(f"Lỗi khởi động Engine: {e}")

    def update_engine_options(self):
        if self.engine:
            try:
                self.engine.configure({
                    "UCI_LimitStrength": True,
                    "UCI_Elo": self.ELO
                })
            except:
                pass

    def rebuild_ui(self):
        self.BOARD_PIXEL = self.SQUARE_SIZE * 8
        w = self.BAR_WIDTH + self.BOARD_PIXEL
        h = self.TITLE_HEIGHT + self.BOARD_PIXEL + self.INFO_HEIGHT
        self.canvas.config(width=w, height=h)
        self.refresh_ui()

    def refresh_ui(self, score=0.0, best_move=None, is_mate=False, is_book=False):
        self.canvas.delete("all")
        off_x, off_y = self.BAR_WIDTH, self.TITLE_HEIGHT

        self.draw_eval_bar(score, is_mate, is_book)

        self.canvas.create_rectangle(0, 0, off_x + self.BOARD_PIXEL, off_y, fill="#222222")
        title = self.canvas.create_text(
            (off_x + self.BOARD_PIXEL)//2,
            off_y//2,
            text="::: DRAG HERE :::",
            fill="#666666",
            font=("Arial", 7, "bold")
        )
        self.canvas.tag_bind(title, "<ButtonPress-1>", self._start_drag)
        self.canvas.tag_bind(title, "<B1-Motion>", self._do_drag)

        for r in range(8):
            for c in range(8):
                x1 = off_x + c * self.SQUARE_SIZE
                y1 = off_y + r * self.SQUARE_SIZE
                color = "#2b2b2b" if (r+c)%2==0 else "#1e1e1e"
                self.canvas.create_rectangle(
                    x1, y1,
                    x1+self.SQUARE_SIZE,
                    y1+self.SQUARE_SIZE,
                    fill=color,
                    outline=""
                )

        if self.selected_square is not None:
            tx, ty = self.get_sq_center(self.selected_square)
            self.canvas.create_rectangle(
                tx-self.SQUARE_SIZE//2,
                ty-self.SQUARE_SIZE//2,
                tx+self.SQUARE_SIZE//2,
                ty+self.SQUARE_SIZE//2,
                outline="#00ffff",
                width=2
            )

        for sq in chess.SQUARES:
            p = self.board.piece_at(sq)
            if p:
                x, y = self.get_sq_center(sq)
                color = "#ffffff" if p.color == chess.WHITE else "#ffcc00"
                self.canvas.create_text(
                    x, y,
                    text=PIECES[p.symbol()],
                    fill=color,
                    font=("Arial", int(self.SQUARE_SIZE*0.65), "bold")
                )

        info_y = off_y + self.BOARD_PIXEL

        if is_book:
            eval_str = "BOOK"
        elif is_mate:
            eval_str = f"MATE {int(score)}"
        else:
            eval_str = f"{score:+.2f}"

        self.canvas.create_text(
            10, info_y+20,
            anchor="w",
            text=f"ELO: {self.ELO} | Depth: {self.DEPTH}",
            fill="#888888",
            font=("Consolas", 9)
        )
        self.canvas.create_text(
            10, info_y+40,
            anchor="w",
            text=f"Eval: {eval_str}",
            fill="#ffffff",
            font=("Consolas", 11, "bold")
        )

        move_str = f"Best: {best_move}" if best_move else "Best: ..."
        self.canvas.create_text(
            10, info_y+60,
            anchor="w",
            text=move_str,
            fill="#00aaff" if is_book else "#00ff00",
            font=("Consolas", 10)
        )

        if best_move:
            x1, y1 = self.get_sq_center(best_move.from_square)
            x2, y2 = self.get_sq_center(best_move.to_square)
            c_arrow = "#00aaff" if is_book else "#00ff00"
            self.canvas.create_line(
                x1, y1, x2, y2,
                fill=c_arrow,
                width=3,
                arrow=tk.LAST
            )

        if self.pending_promotion:
            self.draw_promotion_menu()

    def draw_eval_bar(self, score, is_mate, is_book):
        full_h = self.BOARD_PIXEL
        if is_book:
            percent = 0.5
        elif is_mate:
            percent = 1.0 if score > 0 else 0.0
        else:
            try:
                percent = 1 / (1 + math.exp(-0.5 * score))
            except:
                percent = 1.0 if score > 0 else 0.0

        bar_h = int(percent * full_h)

        self.canvas.create_rectangle(
            0, self.TITLE_HEIGHT,
            self.BAR_WIDTH,
            self.TITLE_HEIGHT + full_h,
            fill="#333333",
            outline=""
        )

        if self.flipped:
            self.canvas.create_rectangle(
                0, self.TITLE_HEIGHT,
                self.BAR_WIDTH,
                self.TITLE_HEIGHT + bar_h,
                fill="#eeeeee",
                outline=""
            )
        else:
            self.canvas.create_rectangle(
                0,
                self.TITLE_HEIGHT + full_h - bar_h,
                self.BAR_WIDTH,
                self.TITLE_HEIGHT + full_h,
                fill="#eeeeee",
                outline=""
            )

    def draw_promotion_menu(self):
        off_x, off_y = self.BAR_WIDTH, self.TITLE_HEIGHT
        menu_w = self.SQUARE_SIZE * 4
        x1 = off_x + (self.BOARD_PIXEL - menu_w) // 2
        y1 = off_y + (self.BOARD_PIXEL - self.SQUARE_SIZE) // 2

        self.canvas.create_rectangle(
            x1-5, y1-20,
            x1+menu_w+5,
            y1+self.SQUARE_SIZE+5,
            fill="#222222",
            outline="#00ff00",
            width=2
        )
        self.canvas.create_text(
            x1+menu_w//2,
            y1-10,
            text="RECOMMENDED",
            fill="#00ff00",
            font=("Arial", 8, "bold")
        )

        pieces = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT]
        syms = ['Q','R','B','N'] if self.board.turn == chess.WHITE else ['q','r','b','n']

        for i, pt in enumerate(pieces):
            px = x1 + i*self.SQUARE_SIZE
            is_best = (pt == self.best_promo_piece)
            bg = "#004400" if is_best else "#333333"
            self.canvas.create_rectangle(
                px, y1,
                px+self.SQUARE_SIZE,
                y1+self.SQUARE_SIZE,
                fill=bg,
                outline="#555555"
            )
            txt = self.canvas.create_text(
                px+self.SQUARE_SIZE//2,
                y1+self.SQUARE_SIZE//2,
                text=PIECES[syms[i]],
                fill="white",
                font=("Arial", int(self.SQUARE_SIZE*0.6))
            )
            self.canvas.tag_bind(txt, "<Button-1>", lambda e, p=pt: self.finish_promotion(p))

    def on_click(self, event):
        if self.click_through or self.pending_promotion:
            return

        off_x, off_y = self.BAR_WIDTH, self.TITLE_HEIGHT
        if event.x < off_x or event.y < off_y or event.y > off_y + self.BOARD_PIXEL:
            return

        c = (event.x - off_x) // self.SQUARE_SIZE
        r = (event.y - off_y) // self.SQUARE_SIZE
        sq = chess.square(7-c, r) if self.flipped else chess.square(c, 7-r)

        if self.selected_square is None:
            p = self.board.piece_at(sq)
            if p and p.color == self.board.turn:
                self.selected_square = sq
                self.refresh_ui()
        else:
            move = chess.Move(self.selected_square, sq)
            p = self.board.piece_at(self.selected_square)

            if p and p.piece_type == chess.PAWN and chess.square_rank(sq) in [0, 7]:
                if chess.Move(self.selected_square, sq, promotion=chess.QUEEN) in self.board.legal_moves:
                    self.pending_promotion = (self.selected_square, sq)
                    threading.Thread(target=self.analyze_promotion, daemon=True).start()
                    self.refresh_ui()
                    return

            if move in self.board.legal_moves:
                self.board.push(move)
                self.selected_square = None
                self.trigger_analysis()
            else:
                self.selected_square = sq if (self.board.piece_at(sq) and self.board.piece_at(sq).color == self.board.turn) else None

            self.refresh_ui()

    def finish_promotion(self, piece_type):
        f, t = self.pending_promotion
        self.board.push(chess.Move(f, t, promotion=piece_type))
        self.pending_promotion = None
        self.selected_square = None
        self.trigger_analysis()
        self.refresh_ui()

    def trigger_analysis(self):
        threading.Thread(target=self._analyze_process, daemon=True).start()

    def _analyze_process(self):
        if self.book_reader:
            try:
                entry = self.book_reader.find(self.board)
                self.root.after(0, lambda: self.refresh_ui(0.0, entry.move, False, True))
                return
            except:
                pass

        if self.engine:
            with self.engine_lock:
                try:
                    info = self.engine.analyse(
                        self.board,
                        chess.engine.Limit(time=0.1)
                    )
                    best = info.get("pv", [None])[0]
                    score = info["score"].relative

                    is_mate = score.is_mate()
                    if is_mate:
                        s_val = score.score()
                    else:
                        s_val = score.score() / 100.0

                    self.root.after(0, lambda: self.refresh_ui(s_val, best, is_mate, False))
                except:
                    pass

    def analyze_promotion(self):
        if not self.engine:
            return

        f, t = self.pending_promotion
        best_s = -9999
        best_p = chess.QUEEN

        for pt in [chess.QUEEN, chess.KNIGHT, chess.ROOK, chess.BISHOP]:
            self.board.push(chess.Move(f, t, promotion=pt))
            try:
                info = self.engine.analyse(self.board, chess.engine.Limit(time=0.05))
                s = info["score"].relative.score()
                if s is not None and s > best_s:
                    best_s = s
                    best_p = pt
            except:
                pass
            self.board.pop()

        self.best_promo_piece = best_p
        self.root.after(0, self.refresh_ui)

    def get_sq_center(self, sq):
        f, r = chess.square_file(sq), chess.square_rank(sq)
        dc = 7-f if self.flipped else f
        dr = r if self.flipped else 7-r
        return (
            self.BAR_WIDTH + dc*self.SQUARE_SIZE + self.SQUARE_SIZE//2,
            self.TITLE_HEIGHT + dr*self.SQUARE_SIZE + self.SQUARE_SIZE//2
        )

    def change_size(self, d):
        self.SQUARE_SIZE = max(30, min(120, self.SQUARE_SIZE + d))
        self.rebuild_ui()

    def change_elo(self, d):
        self.ELO = max(100, min(self.max_elo, self.ELO + d))
        self.update_engine_options()
        self.trigger_analysis()
        self.refresh_ui()

    def toggle_flip(self):
        self.flipped = not self.flipped
        self.refresh_ui()

    def undo_move(self):
        if self.board.move_stack:
            self.board.pop()
            self.selected_square = None
            self.trigger_analysis()
            self.refresh_ui()

    def reset_board(self):
        self.board.reset()
        self.trigger_analysis()
        self.refresh_ui()

    def prompt_paths(self):
        p = filedialog.askopenfilename(title="Chọn Stockfish (.exe)")
        if p:
            self.config["engine_path"] = p
            b = filedialog.askopenfilename(
                title="Chọn Book (.bin) [Optional]",
                filetypes=[("Polyglot Book", "*.bin")]
            )
            if b:
                self.config["book_path"] = b
            self.save_config()
            self.init_engine_system()

    def toggle_click_through(self):
        self.click_through = not self.click_through
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, -20,
            (style | 0x80000 | 0x20) if self.click_through else (style & ~0x20)
        )
        self.root.attributes("-alpha", 0.3 if self.click_through else 0.8)

    def _start_drag(self, e):
        self._dx, self._dy = e.x, e.y

    def _do_drag(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    def quit(self):
        keyboard.unhook_all()
        if self.engine:
            self.engine.quit()
        self.root.destroy()

if __name__ == "__main__":
    ChessOverlay().root.mainloop()
