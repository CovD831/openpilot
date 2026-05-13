import curses
import random
import time

class Snake:
    def __init__(self, start_x, start_y):
        self.body = [(start_x, start_y)]
        self.direction = (1, 0)  # moving right
        self.grow_flag = False

    def move(self):
        head = self.body[-1]
        new_head = (head[0] + self.direction[0], head[1] + self.direction[1])
        self.body.append(new_head)
        if not self.grow_flag:
            self.body.pop(0)
        else:
            self.grow_flag = False

    def grow(self):
        self.grow_flag = True

    def check_collision(self, width, height):
        head = self.body[-1]
        # wall collision
        if head[0] < 0 or head[0] >= width or head[1] < 0 or head[1] >= height:
            return True
        # self collision
        if head in self.body[:-1]:
            return True
        return False

    def set_direction(self, dx, dy):
        # prevent reversing
        if (dx, dy) != (-self.direction[0], -self.direction[1]):
            self.direction = (dx, dy)


class Food:
    def __init__(self, width, height, snake_body):
        self.position = None
        self.place(width, height, snake_body)

    def place(self, width, height, snake_body):
        while True:
            x = random.randint(0, width-1)
            y = random.randint(0, height-1)
            if (x, y) not in snake_body:
                self.position = (x, y)
                break


class Game:
    def __init__(self, width=20, height=20):
        self.width = width
        self.height = height
        self.snake = Snake(width//2, height//2)
        self.food = Food(width, height, self.snake.body)
        self.score = 0
        self.game_over = False

    def update(self):
        self.snake.move()
        if self.snake.check_collision(self.width, self.height):
            self.game_over = True
            return
        if self.snake.body[-1] == self.food.position:
            self.snake.grow()
            self.score += 1
            self.food.place(self.width, self.height, self.snake.body)

    def get_state(self):
        grid = [[0 for _ in range(self.width)] for _ in range(self.height)]
        for segment in self.snake.body:
            grid[segment[1]][segment[0]] = 1
        grid[self.food.position[1]][self.food.position[0]] = 2
        return grid


def draw(stdscr, game):
    stdscr.clear()
    grid = game.get_state()
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == 0:
                stdscr.addch(y, x, '.')
            elif cell == 1:
                stdscr.addch(y, x, 'S')
            elif cell == 2:
                stdscr.addch(y, x, 'F')
    stdscr.addstr(game.height, 0, f'Score: {game.score}')
    if game.game_over:
        stdscr.addstr(game.height+1, 0, 'Game Over! Press any key to exit.')
    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(1)
    game = Game(20, 20)
    draw(stdscr, game)
    while not game.game_over:
        key = stdscr.getch()
        if key == curses.KEY_UP:
            game.snake.set_direction(0, -1)
        elif key == curses.KEY_DOWN:
            game.snake.set_direction(0, 1)
        elif key == curses.KEY_LEFT:
            game.snake.set_direction(-1, 0)
        elif key == curses.KEY_RIGHT:
            game.snake.set_direction(1, 0)
        elif key == ord('q'):
            break
        game.update()
        draw(stdscr, game)
        time.sleep(0.1)
    stdscr.nodelay(0)
    stdscr.getch()

if __name__ == '__main__':
    curses.wrapper(main)
