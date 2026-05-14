#!/usr/bin/env python3
"""
Snake game built with pygame (standalone GUI).
Controls: Arrow keys to move, R to restart, Q or Esc to quit, P to pause/resume.
Start screen on launch; press any key or click to begin.
"""
import pygame
import sys
import random

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
GRID_SIZE = 20
CELL_COUNT = 20
WIDTH = GRID_SIZE * CELL_COUNT
HEIGHT = GRID_SIZE * CELL_COUNT

BACKGROUND_COLOR = (0, 0, 0)
GRID_COLOR = (40, 40, 40)
SNAKE_HEAD_COLOR = (0, 255, 0)
SNAKE_HEAD_OUTLINE = (0, 100, 0)
SNAKE_COLOR = (0, 200, 0)
SNAKE_OUTLINE = (0, 100, 0)
FOOD_COLOR = (255, 0, 0)
FOOD_OUTLINE = (150, 0, 0)
TEXT_COLOR = (255, 255, 255)
OVERLAY_ALPHA = 128

DIRECTIONS = {
    "Up": (0, -1),
    "Down": (0, 1),
    "Left": (-1, 0),
    "Right": (1, 0),
}


class SnakeGame:
    """Main game class – start screen, gameplay, game over."""

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Snake")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 40)
        self.small_font = pygame.font.Font(None, 24)

        # Game state
        self.state = "start"         # "start", "playing", "game_over"
        self.paused = False
        self.snake = []
        self.direction = "Right"
        self.next_direction = "Right"
        self.food = None
        self.score = 0
        self.last_move = 0
        self.pause_start = 0

        self.reset_game()
        self.last_move = pygame.time.get_ticks()

    def reset_game(self):
        """Reset all game variables for a new game."""
        self.snake = [(CELL_COUNT // 2, CELL_COUNT // 2)]
        self.direction = "Right"
        self.next_direction = "Right"
        self.food = None
        self.score = 0
        self.paused = False
        self.place_food()

    def place_food(self):
        """Place food at a random empty cell."""
        while True:
            x = random.randint(0, CELL_COUNT - 1)
            y = random.randint(0, CELL_COUNT - 1)
            if (x, y) not in self.snake:
                self.food = (x, y)
                return

    def get_interval(self):
        """Return current move interval (ms) – decreases with score."""
        interval = 150 - (self.score // 5) * 10
        return max(50, interval)

    def move_snake(self):
        """Advance the snake one cell in the current direction."""
        self.direction = self.next_direction
        dx, dy = DIRECTIONS[self.direction]
        head = self.snake[0]
        new_head = (head[0] + dx, head[1] + dy)

        # Collision detection
        if (new_head in self.snake or
                new_head[0] < 0 or new_head[0] >= CELL_COUNT or
                new_head[1] < 0 or new_head[1] >= CELL_COUNT):
            self.state = "game_over"
            return

        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 1
            self.place_food()
        else:
            self.snake.pop()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit_game()

            elif event.type == pygame.KEYDOWN:
                key = event.key

                # Quit always available
                if key in (pygame.K_q, pygame.K_ESCAPE):
                    self.quit_game()

                elif self.state == "start":
                    self.start_game()

                elif self.state == "game_over":
                    if key == pygame.K_r:
                        self.start_game()
                    else:
                        self.state = "start"  # go back to start screen

                elif self.state == "playing":
                    if key == pygame.K_UP:
                        self.change_direction("Up")
                    elif key == pygame.K_DOWN:
                        self.change_direction("Down")
                    elif key == pygame.K_LEFT:
                        self.change_direction("Left")
                    elif key == pygame.K_RIGHT:
                        self.change_direction("Right")
                    elif key == pygame.K_p:
                        if self.paused:
                            self.paused = False
                            self.last_move = pygame.time.get_ticks()
                        else:
                            self.paused = True
                            self.pause_start = pygame.time.get_ticks()
                    elif key == pygame.K_r:
                        self.start_game()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if self.state == "start":
                    self.start_game()

    def start_game(self):
        """Transition to playing state with a fresh game."""
        self.reset_game()
        self.state = "playing"
        self.paused = False
        self.last_move = pygame.time.get_ticks()

    def change_direction(self, new_dir):
        """Change direction if not reversing."""
        dx, dy = DIRECTIONS[new_dir]
        cur_dx, cur_dy = DIRECTIONS[self.direction]
        if (dx, dy) != (-cur_dx, -cur_dy):
            self.next_direction = new_dir

    def quit_game(self):
        pygame.quit()
        sys.exit()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def draw(self):
        self.screen.fill(BACKGROUND_COLOR)
        if self.state == "start":
            self._draw_start_screen()
        elif self.state == "game_over":
            self._draw_game_board()
            self._draw_overlay("GAME OVER", "Press R to restart  Any key for start")
        else:  # playing (including paused)
            self._draw_game_board()
            if self.paused:
                self._draw_overlay("PAUSED", "Press P to resume")

    def _draw_start_screen(self):
        """Draw the start screen with title and instructions."""
        title = self.font.render("SNAKE", True, TEXT_COLOR)
        self.screen.blit(title, (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 60))
        instructions = [
            "Use arrow keys to move",
            "P to pause",
            "Press any key or click to start",
        ]
        y = HEIGHT // 2
        for line in instructions:
            text = self.small_font.render(line, True, TEXT_COLOR)
            self.screen.blit(text, (WIDTH // 2 - text.get_width() // 2, y))
            y += 30

    def _draw_game_board(self):
        """Draw the grid, snake, food, and score."""
        # Grid
        for x in range(0, WIDTH, GRID_SIZE):
            pygame.draw.line(self.screen, GRID_COLOR, (x, 0), (x, HEIGHT))
        for y in range(0, HEIGHT, GRID_SIZE):
            pygame.draw.line(self.screen, GRID_COLOR, (0, y), (WIDTH, y))

        # Snake
        for i, (x, y) in enumerate(self.snake):
            rect = (x * GRID_SIZE + 1, y * GRID_SIZE + 1, GRID_SIZE - 2, GRID_SIZE - 2)
            if i == 0:  # head
                pygame.draw.rect(self.screen, SNAKE_HEAD_COLOR, rect)
                pygame.draw.rect(self.screen, SNAKE_HEAD_OUTLINE, rect, 2)
            else:
                pygame.draw.rect(self.screen, SNAKE_COLOR, rect)
                pygame.draw.rect(self.screen, SNAKE_OUTLINE, rect, 1)

        # Food
        if self.food:
            fx, fy = self.food
            cx = fx * GRID_SIZE + GRID_SIZE // 2
            cy = fy * GRID_SIZE + GRID_SIZE // 2
            r = GRID_SIZE // 2 - 2
            pygame.draw.circle(self.screen, FOOD_COLOR, (cx, cy), r)
            pygame.draw.circle(self.screen, FOOD_OUTLINE, (cx, cy), r, 2)

        # Score
        score_text = self.small_font.render(f"Score: {self.score}", True, TEXT_COLOR)
        self.screen.blit(score_text, (10, 10))

    def _draw_overlay(self, line1, line2):
        """Semi-transparent overlay with two centered lines."""
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, OVERLAY_ALPHA))
        self.screen.blit(overlay, (0, 0))
        text1 = self.font.render(line1, True, TEXT_COLOR)
        text2 = self.small_font.render(line2, True, TEXT_COLOR)
        self.screen.blit(text1, (WIDTH // 2 - text1.get_width() // 2, HEIGHT // 2 - 20))
        self.screen.blit(text2, (WIDTH // 2 - text2.get_width() // 2, HEIGHT // 2 + 20))

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        """Main game loop."""
        while True:
            self.clock.tick(60)  # 60 FPS
            now = pygame.time.get_ticks()

            self.handle_events()

            # Update game state
            if self.state == "playing" and not self.paused:
                if now - self.last_move >= self.get_interval():
                    self.move_snake()
                    self.last_move = now

            self.draw()
            pygame.display.flip()


if __name__ == "__main__":
    SnakeGame().run()