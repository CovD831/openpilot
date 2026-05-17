#!/usr/bin/env python3
"""
贪吃蛇游戏 - 使用 Pygame 实现
独立窗口，方向键控制，红色食物，得分显示，游戏结束画面（R/Q重新开始/退出）
支持 --test 用于快速测试（2秒后自动退出）
在非交互式终端中自动启用测试模式，避免 CI 或无终端环境挂起。
"""

import argparse
import pygame
import random
import sys
import time

# 常量
CELL_SIZE = 20
GRID_WIDTH = 30
GRID_HEIGHT = 20
WINDOW_WIDTH = GRID_WIDTH * CELL_SIZE
WINDOW_HEIGHT = GRID_HEIGHT * CELL_SIZE
FPS = 10  # 游戏速度（帧率）
AUTO_QUIT_DELAY = 5   # 游戏结束后未操作时自动退出等待秒数
TEST_DURATION = 2.0   # 测试模式自动退出时间（秒）

# 颜色 (R, G, B)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
DARK_GREEN = (0, 150, 0)

# 方向常量
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)


class SnakeGame:
    def __init__(self, test_mode=False):
        self.test_mode = test_mode
        pygame.init()
        self.screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
        pygame.display.set_caption("贪吃蛇 - Snake")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 36)
        self.reset_game()

    def reset_game(self):
        """重置游戏状态"""
        # 蛇：初始三个节点，方向向右
        self.snake = [(GRID_WIDTH // 2, GRID_HEIGHT // 2),
                      (GRID_WIDTH // 2 - 1, GRID_HEIGHT // 2),
                      (GRID_WIDTH // 2 - 2, GRID_HEIGHT // 2)]
        self.direction = RIGHT
        self.score = 0
        self.game_over = False
        self.game_over_time = None   # 记录 game over 发生的时刻
        self.food = self.new_food()
        self.start_time = time.time()   # 用于测试模式自动退出

    def new_food(self):
        """生成一个不在蛇身上的食物位置"""
        while True:
            fx = random.randint(0, GRID_WIDTH - 1)
            fy = random.randint(0, GRID_HEIGHT - 1)
            if (fx, fy) not in self.snake:
                return (fx, fy)

    def handle_input(self):
        """处理键盘事件"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if self.game_over:
                    if event.key == pygame.K_r:
                        self.reset_game()
                    elif event.key == pygame.K_q:
                        return False
                else:
                    # 方向控制（箭头键或 WASD）
                    if event.key in (pygame.K_UP, pygame.K_w) and self.direction != DOWN:
                        self.direction = UP
                    elif event.key in (pygame.K_DOWN, pygame.K_s) and self.direction != UP:
                        self.direction = DOWN
                    elif event.key in (pygame.K_LEFT, pygame.K_a) and self.direction != RIGHT:
                        self.direction = LEFT
                    elif event.key in (pygame.K_RIGHT, pygame.K_d) and self.direction != LEFT:
                        self.direction = RIGHT
        return True

    def update(self):
        """更新游戏逻辑"""
        if self.game_over:
            return

        # 计算新蛇头
        head_x, head_y = self.snake[0]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)

        # 碰撞检测：撞墙或自身
        if (new_head[0] < 0 or new_head[0] >= GRID_WIDTH or
            new_head[1] < 0 or new_head[1] >= GRID_HEIGHT or
            new_head in self.snake):
            self.game_over = True
            self.game_over_time = time.time()
            return

        # 移动蛇
        self.snake.insert(0, new_head)

        # 检查是否吃到食物
        if new_head == self.food:
            self.score += 1
            self.food = self.new_food()
        else:
            self.snake.pop()

    def draw(self):
        """绘制画面"""
        self.screen.fill(BLACK)

        # 绘制网格线
        for x in range(0, WINDOW_WIDTH, CELL_SIZE):
            pygame.draw.line(self.screen, (40, 40, 40), (x, 0), (x, WINDOW_HEIGHT))
        for y in range(0, WINDOW_HEIGHT, CELL_SIZE):
            pygame.draw.line(self.screen, (40, 40, 40), (0, y), (WINDOW_WIDTH, y))

        # 绘制蛇
        for i, segment in enumerate(self.snake):
            rect = pygame.Rect(segment[0]*CELL_SIZE, segment[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE)
            if i == 0:
                pygame.draw.rect(self.screen, GREEN, rect)    # 蛇头绿色
            else:
                pygame.draw.rect(self.screen, DARK_GREEN, rect) # 身体深绿

        # 绘制食物（红色方块）
        food_rect = pygame.Rect(self.food[0]*CELL_SIZE, self.food[1]*CELL_SIZE, CELL_SIZE, CELL_SIZE)
        pygame.draw.rect(self.screen, RED, food_rect)

        # 绘制分数
        score_text = self.font.render(f"Score: {self.score}", True, WHITE)
        self.screen.blit(score_text, (10, 10))

        # 如果游戏结束，绘制结束画面
        if self.game_over:
            overlay = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))   # 半透明黑色
            self.screen.blit(overlay, (0, 0))

            game_over_text = self.font.render("Game Over!", True, WHITE)
            score_text2 = self.font.render(f"Final Score: {self.score}", True, WHITE)
            restart_text = self.font.render("Press R to restart, Q to quit", True, WHITE)

            # 居中显示
            self.screen.blit(game_over_text, (WINDOW_WIDTH//2 - game_over_text.get_width()//2,
                                              WINDOW_HEIGHT//2 - 60))
            self.screen.blit(score_text2, (WINDOW_WIDTH//2 - score_text2.get_width()//2,
                                           WINDOW_HEIGHT//2 - 20))
            self.screen.blit(restart_text, (WINDOW_WIDTH//2 - restart_text.get_width()//2,
                                            WINDOW_HEIGHT//2 + 20))

        pygame.display.flip()

    def run(self):
        """主游戏循环"""
        running = True
        while running:
            running = self.handle_input()
            self.update()
            self.draw()
            # 游戏结束后无操作自动退出
            if self.game_over and self.game_over_time is not None:
                if time.time() - self.game_over_time > AUTO_QUIT_DELAY:
                    running = False
            # 测试模式：到达指定时间后自动退出
            if self.test_mode and time.time() - self.start_time > TEST_DURATION:
                running = False
            self.clock.tick(FPS)
        pygame.quit()
        sys.exit()


def main():
    parser = argparse.ArgumentParser(description="贪吃蛇游戏")
    parser.add_argument('--test', action='store_true',
                        help='测试模式：运行2秒后自动退出')
    args = parser.parse_args()

    # 非交互式终端（如CI环境）中自动启用测试模式以免挂起
    test_mode = args.test or not sys.stdin.isatty()

    # 检查显示是否可用（避免无头系统上崩溃）
    try:
        pygame.display.set_mode((1, 1))
        pygame.quit()
    except pygame.error:
        print("错误：无法初始化显示。请确保有可用的图形环境。")
        sys.exit(1)

    game = SnakeGame(test_mode=test_mode)
    game.run()


if __name__ == "__main__":
    main()