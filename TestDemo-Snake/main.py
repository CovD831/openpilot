import tkinter as tk
import random

CELL, W, H, SPEED = 20, 30, 20, 150
snake, food, dr, score, over = [], None, 'Right', 0, False
canvas, root = None, None


def init():
    global snake, food, dr, score, over
    # initial snake: head at (W//4, H//2) going right
    snake = [(W // 4, H // 2), (W // 4 - 1, H // 2), (W // 4 - 2, H // 2)]
    dr, score, over = 'Right', 0, False
    food = new_food()
    root.title(f"Snake - Score: {score}")
    draw()
    if not over:
        canvas.after(SPEED, move)


def new_food():
    while True:
        x, y = random.randint(0, W - 1), random.randint(0, H - 1)
        if (x, y) not in snake:
            return (x, y)


def change(new_dir):
    global dr
    opp = {'Up': 'Down', 'Down': 'Up', 'Left': 'Right', 'Right': 'Left'}
    if new_dir != opp.get(dr):
        dr = new_dir


def move():
    global snake, food, score, over
    if over:
        return
    hx, hy = snake[0]
    dx, dy = {'Up': (0, -1), 'Down': (0, 1), 'Left': (-1, 0), 'Right': (1, 0)}[dr]
    nh = (hx + dx, hy + dy)
    # wall collision
    if not (0 <= nh[0] < W and 0 <= nh[1] < H):
        over = True
        draw()
        return
    # self collision (exclude tail because it will pop)
    if nh in snake[:-1]:
        over = True
        draw()
        return
    snake.insert(0, nh)
    if nh == food:
        score += 1
        root.title(f"Snake - Score: {score}")
        food = new_food()
    else:
        snake.pop()
    draw()
    if not over:
        canvas.after(SPEED, move)


def draw():
    canvas.delete('all')
    # draw snake
    for i, (x, y) in enumerate(snake):
        color = '#4CAF50' if i == 0 else '#8BC34A'
        canvas.create_rectangle(x * CELL + 1, y * CELL + 1,
                                x * CELL + CELL - 1, y * CELL + CELL - 1,
                                fill=color, outline='')
    # draw food
    if food:
        x, y = food
        canvas.create_oval(x * CELL + 2, y * CELL + 2,
                           x * CELL + CELL - 2, y * CELL + CELL - 2,
                           fill='#FF5252', outline='')
    # game over text
    if over:
        canvas.create_text(W * CELL // 2, H * CELL // 2,
                           text="Game Over!\nR:Restart  Q:Quit",
                           fill='white', font=('Arial', 16, 'bold'),
                           justify='center')


def key(e):
    k = e.keysym
    if k in ('Up', 'Down', 'Left', 'Right') and not over:
        change(k)
    elif k.lower() == 'r' and over:
        init()
    elif k.lower() == 'q' or k == 'Escape':
        root.destroy()


def main():
    global canvas, root
    root = tk.Tk()
    root.title("Snake")
    canvas = tk.Canvas(root, width=W * CELL, height=H * CELL,
                       bg='black', highlightthickness=0)
    canvas.pack()
    root.bind('<Key>', key)
    init()
    root.mainloop()


if __name__ == '__main__':
    main()