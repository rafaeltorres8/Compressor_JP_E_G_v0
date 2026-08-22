import tkinter as tk
from gui import ImageCompressorApp

def main() -> None:
    root = tk.Tk()
    ImageCompressorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()