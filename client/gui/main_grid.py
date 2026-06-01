
"""Module thiết kế giao diện lưới hiển thị video."""

import tkinter as tk


class MainGrid(tk.Frame):
    """Lớp tạo bố cục lưới tĩnh gồm 6 ô vuông để hiển thị video."""

    def __init__(self, parent):
        """Khởi tạo cấu trúc lưới 6 ô."""
        super().__init__(parent, bg="black")
        self.pack(fill=tk.BOTH, expand=True)
        self.create_grid()

    def create_grid(self):
        """Thiết kế cấu trúc Grid Layout 2 hàng x 3 cột (6 ô)."""
        for i in range(3):
            self.columnconfigure(i, weight=1)
        for i in range(2):
            self.rowconfigure(i, weight=1)

        for row in range(2):
            for col in range(3):
                index = row * 3 + col + 1
                cell = tk.Frame(
                    self,
                    highlightbackground="gray",
                    highlightthickness=2,
                    bg="#1e1e1e"
                )
                cell.grid(row=row, column=col, sticky="nsew", padx=5, py=5)

                label = tk.Label(
                    cell,
                    text=f"Video Stream {index}",
                    fg="white",
                    bg="#1e1e1e"
                )
                label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)


if __name__ == "__main__":
    root = tk.Tk()
    root.title("HexaCall - Main Grid Layout Test")
    root.geometry("800x600")
    app = MainGrid(root)
    root.mainloop()