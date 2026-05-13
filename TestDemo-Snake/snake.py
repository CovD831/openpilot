import curses
import random
import time

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(100)

    sh, sw = stdscr.getmaxyx()
    w = curses.newwin(sh, sw, 0, 0)
    w.keypad(1)
    w.border(0)

    snake = [[sh//2, sw//2], [sh//2, sw//2-1], [sh//2, sw//2-2]]
    food = [sh//2, sw//2+5]
    w.addch(food[0], food[1], curses.ACS_PI)

    key = curses.KEY_RIGHT
    score = 0

    while True:
        w.border(0)
        w.addstr(0, 2, f'Score: {score}')

        next_key = w.getch()
        if next_key != -1:
            if (key == curses.KEY_RIGHT and next_key != curses.KEY_LEFT) or (key == curses.KEY_LEFT and next_key != curses.KEY_RIGHT) or (key == curses.KEY_UP and next_key != curses.KEY_DOWN) or (key == curses.KEY_DOWN and next_key != curses.KEY_UP):
                key = next_key

        head = snake[0][:]
        if key == curses.KEY_RIGHT:
            head[1] += 1
        elif key == curses.KEY_LEFT:
            head[1] -= 1
        elif key == curses.KEY_UP:
            head[0] -= 1
        elif key == curses.KEY_DOWN:
            head[0] += 1

        if head in snake or head[0] == 0 or head[0] == sh-1 or head[1] == 0 or head[1] == sw-1:
            w.addstr(sh//2, sw//2-5, 'GAME OVER')
            w.refresh()
            time.sleep(2)
            break

        snake.insert(0, head)

        if head == food:
            score += 10
            food = None
            while food is None:
                nf = [random.randint(1, sh-2), random.randint(1, sw-2)]
                if nf not in snake:
                    food = nf
            w.addch(food[0], food[1], curses.ACS_PI)
        else:
            tail = snake.pop()
            w.addch(tail[0], tail[1], ' ')

        w.addch(head[0], head[1], curses.ACS_BLOCK)

if __name__ == '__main__':
    curses.wrapper(main)