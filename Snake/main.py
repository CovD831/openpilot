import os
import sys
import random

# Prevent pygame import from hanging in headless CI environments.
# Set dummy SDL driver if no display is available (non-Windows).
if sys.platform != 'win32' and 'DISPLAY' not in os.environ:
    os.environ['SDL_VIDEODRIVER'] = 'dummy'

try:
    import pygame
except ImportError:
    print("Error: pygame is not installed.", file=sys.stderr)
    print("Install it using: pip install pygame", file=sys.stderr)
    sys.exit(1)

# --- Constants ---
CELL = 20
COLS, ROWS = 20, 20
GRID_WIDTH = COLS * CELL
GRID_HEIGHT = ROWS * CELL
INFO_HEIGHT = 40
WIN_WIDTH = GRID_WIDTH
WIN_HEIGHT = GRID_HEIGHT + INFO_HEIGHT

FPS = 10

# Colors (R, G, B)
BLACK = (0, 0, 0)
GREEN = (0, 255, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
WHITE = (255, 255, 255)
DARK_GREEN = (0, 150, 0)
DARK_GRAY = (40, 40, 40)

# Directions
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

# Number of frames to wait after game over before auto‑exit
AUTO_EXIT_FRAMES = 30

# --- Game State (Global) ---
snake = [(COLS // 2, ROWS // 2),
         (COLS // 2 - 1, ROWS // 2),
         (COLS // 2 - 2, ROWS // 2)]
direction = RIGHT
score = 0
game_over = False
food = None
game_over_frame = 0


# --- Helper Functions ---
def create_food():
    """Place a food item in a random unoccupied cell."""
    global food
    occupied = set(snake)
    available = [(x, y) for x in range(COLS) for y in range(ROWS) if (x, y) not in occupied]
    food = random.choice(available) if available else None


def draw(screen, font):
    """Render the game state onto the pygame window."""
    grid_surface = pygame.Surface((GRID_WIDTH, GRID_HEIGHT))
    grid_surface.fill(BLACK)

    for i, (x, y) in enumerate(snake):
        rect = (x * CELL, y * CELL, CELL, CELL)
        color = YELLOW if i == 0 else GREEN
        pygame.draw.rect(grid_surface, color, rect)
        if i > 0:
            pygame.draw.rect(grid_surface, DARK_GREEN, rect, 1)

    if food:
        fx, fy = food
        food_rect = (fx * CELL, fy * CELL, CELL, CELL)
        pygame.draw.rect(grid_surface, RED, food_rect)
        pygame.draw.rect(grid_surface, WHITE, food_rect, 2)

    screen.blit(grid_surface, (0, 0))

    pygame.draw.rect(screen, DARK_GRAY, (0, GRID_HEIGHT, WIN_WIDTH, INFO_HEIGHT))
    pygame.draw.line(screen, WHITE, (0, GRID_HEIGHT), (WIN_WIDTH, GRID_HEIGHT), 2)

    score_surf = font.render(f"Score: {score}", True, WHITE)
    screen.blit(score_surf, (10, GRID_HEIGHT + (INFO_HEIGHT - 20) // 2))

    if game_over:
        overlay = pygame.Surface((GRID_WIDTH, GRID_HEIGHT))
        overlay.set_alpha(180)
        overlay.fill(BLACK)
        screen.blit(overlay, (0, 0))

        big_font = pygame.font.Font(None, 48)
        mid_font = pygame.font.Font(None, 24)

        go_text = big_font.render("GAME OVER", True, WHITE)
        inst_text = mid_font.render("R = Restart    Q = Quit", True, WHITE)

        screen.blit(go_text, go_text.get_rect(center=(GRID_WIDTH // 2, GRID_HEIGHT // 2 - 20)))
        screen.blit(inst_text, inst_text.get_rect(center=(GRID_WIDTH // 2, GRID_HEIGHT // 2 + 20)))

    pygame.display.flip()


def step():
    """Advance the game by one tick (move snake, check collisions)."""
    global snake, food, direction, score, game_over

    if game_over:
        return

    head_x, head_y = snake[0]
    dx, dy = direction
    new_head = (head_x + dx, head_y + dy)

    if not (0 <= new_head[0] < COLS and 0 <= new_head[1] < ROWS):
        game_over = True
        return

    if new_head in snake:
        game_over = True
        return

    snake.insert(0, new_head)
    if food and new_head == food:
        score += 1
        create_food()
    else:
        snake.pop()


def reset_game():
    """Reset all game variables to their initial state."""
    global snake, direction, score, game_over, food, game_over_frame
    snake = [(COLS // 2, ROWS // 2),
             (COLS // 2 - 1, ROWS // 2),
             (COLS // 2 - 2, ROWS // 2)]
    direction = RIGHT
    score = 0
    game_over = False
    game_over_frame = 0
    create_food()


def main():
    global direction, game_over_frame

    pygame.init()

    try:
        screen = pygame.display.set_mode((WIN_WIDTH, WIN_HEIGHT))
    except pygame.error as e:
        print(f"Error: Could not create pygame display: {e}", file=sys.stderr)
        print("Make sure you are running in a graphical environment.", file=sys.stderr)
        pygame.quit()
        sys.exit(1)

    pygame.display.set_caption("Snake")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 24)

    # Detect headless (dummy driver) – useful for CI/testing.
    # In headless mode the game will automatically exit after a few frames.
    headless = (pygame.display.get_driver() == 'dummy')
    headless_counter = 0

    create_food()
    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if game_over:
                    if event.key == pygame.K_r:
                        reset_game()
                    elif event.key == pygame.K_q:
                        running = False
                else:
                    if event.key == pygame.K_UP and direction != DOWN:
                        direction = UP
                    elif event.key == pygame.K_DOWN and direction != UP:
                        direction = DOWN
                    elif event.key == pygame.K_LEFT and direction != RIGHT:
                        direction = LEFT
                    elif event.key == pygame.K_RIGHT and direction != LEFT:
                        direction = RIGHT

        step()
        draw(screen, font)

        if game_over:
            game_over_frame += 1
            if game_over_frame > AUTO_EXIT_FRAMES:
                running = False

        # In headless mode, exit after a short while so CI doesn't hang.
        if headless:
            headless_counter += 1
            if headless_counter > 5:
                running = False

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()