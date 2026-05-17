#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A classic Snake game using pygame (standalone GUI window)."""

import random
import sys

try:
    import pygame
except ImportError:
    print("pygame is required. Install it with: pip install pygame")
    sys.exit(1)

# ----------------------------------------------------------------------
# Configuration
CELL_SIZE = 20
GRID_WIDTH = 20
GRID_HEIGHT = 20
WINDOW_WIDTH = CELL_SIZE * GRID_WIDTH
WINDOW_HEIGHT = CELL_SIZE * GRID_HEIGHT
FPS = 15

# Colors (R, G, B)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 200, 0)
DARK_GREEN = (0, 150, 0)
RED = (200, 0, 0)
# Direction vectors
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)


def place_food(snake):
    """Return a random (x, y) cell that is not occupied by the snake."""
    while True:
        x = random.randint(0, GRID_WIDTH - 1)
        y = random.randint(0, GRID_HEIGHT - 1)
        if (x, y) not in snake:
            return (x, y)


def draw_text(surface, text, size, color, center):
    """Helper to draw centered text on a surface."""
    font = pygame.font.SysFont(None, size)
    img = font.render(text, True, color)
    rect = img.get_rect(center=center)
    surface.blit(img, rect)


def reset_game():
    """Return fresh game state for a new game."""
    snake = [
        (GRID_WIDTH // 2, GRID_HEIGHT // 2),
        (GRID_WIDTH // 2 - 1, GRID_HEIGHT // 2),
        (GRID_WIDTH // 2 - 2, GRID_HEIGHT // 2),
    ]
    direction = RIGHT
    food = place_food(snake)
    return snake, direction, food, 0, False


def main():
    """Main entry point: run the game loop once."""
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Snake Game")
    clock = pygame.time.Clock()

    # Initialise game state
    snake, direction, food, score, game_over = reset_game()
    next_direction = direction  # buffered direction change

    running = True
    while running:
        # ------------------------------------------------------------------
        # Event handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if game_over:
                    if event.key == pygame.K_r:
                        snake, direction, food, score, game_over = reset_game()
                        next_direction = direction
                    elif event.key == pygame.K_q:
                        running = False
                else:
                    # Arrow keys – no 180° reversal
                    if event.key == pygame.K_UP and direction != DOWN:
                        next_direction = UP
                    elif event.key == pygame.K_DOWN and direction != UP:
                        next_direction = DOWN
                    elif event.key == pygame.K_LEFT and direction != RIGHT:
                        next_direction = LEFT
                    elif event.key == pygame.K_RIGHT and direction != LEFT:
                        next_direction = RIGHT

        # ------------------------------------------------------------------
        # Game update (if not over)
        if not game_over:
            direction = next_direction
            head = snake[0]
            new_head = (head[0] + direction[0], head[1] + direction[1])

            # Wall collision
            if (new_head[0] < 0 or new_head[0] >= GRID_WIDTH or
                    new_head[1] < 0 or new_head[1] >= GRID_HEIGHT):
                game_over = True
            else:
                # Self‑collision: if we eat, tail stays; otherwise tail is removed.
                will_eat = new_head == food
                if will_eat:
                    # Tail stays → full snake counts (except head, which is old)
                    if new_head in snake:
                        game_over = True
                    else:
                        snake.insert(0, new_head)
                        score += 1
                        food = place_food(snake)
                else:
                    # Tail will be removed – it is safe to move into it
                    if new_head in snake[:-1]:
                        game_over = True
                    else:
                        snake.insert(0, new_head)
                        snake.pop()

        # ------------------------------------------------------------------
        # Drawing
        screen.fill(BLACK)

        # Food (red square)
        fx, fy = food
        food_rect = pygame.Rect(fx * CELL_SIZE, fy * CELL_SIZE,
                                CELL_SIZE, CELL_SIZE)
        pygame.draw.rect(screen, RED, food_rect)

        # Snake body (green, header slightly darker)
        for idx, (sx, sy) in enumerate(snake):
            color = DARK_GREEN if idx == 0 else GREEN
            seg_rect = pygame.Rect(sx * CELL_SIZE, sy * CELL_SIZE,
                                   CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(screen, color, seg_rect)

        # Score overlay (top centre)
        draw_text(screen, f"Score: {score}", 24, WHITE,
                  (WINDOW_WIDTH // 2, 15))

        # Game over overlay
        if game_over:
            # Semi‑transparent overlay
            overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT),
                                     pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 128))
            screen.blit(overlay, (0, 0))

            draw_text(screen, "GAME OVER", 48, WHITE,
                      (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 - 40))
            draw_text(screen, f"Final Score: {score}", 36, WHITE,
                      (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 20))
            draw_text(screen, "Press R to Restart or Q to Quit", 24, WHITE,
                      (WINDOW_WIDTH // 2, WINDOW_HEIGHT // 2 + 70))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()