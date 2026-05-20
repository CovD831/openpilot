import curses, random, sys

def main(s):
    curses.curs_set(0); s.nodelay(1); s.timeout(100)
    h,w = s.getmaxyx()
    if h<10 or w<20: s.addstr(0,0,"Too small"); s.getch(); return
    snake = [(h//2,w//2)]; dir = (0,1); food = None; score = 0
    def place_food():
        while True:
            x = random.randint(1,w-2); y = random.randint(1,h-2)
            if (y,x) not in snake: return (y,x)
    food = place_food()
    demo = '--demo' in sys.argv
    while True:
        k = s.getch()
        if k == ord('q'): break
        if k == curses.KEY_UP and dir != (1,0): dir = (-1,0)
        elif k == curses.KEY_DOWN and dir != (-1,0): dir = (1,0)
        elif k == curses.KEY_LEFT and dir != (0,1): dir = (0,-1)
        elif k == curses.KEY_RIGHT and dir != (0,-1): dir = (0,1)
        if demo:
            head = snake[0]; dy = food[0]-head[0]; dx = food[1]-head[1]
            possible = []
            if dy>0: possible.append((1,0))
            elif dy<0: possible.append((-1,0))
            if dx>0: possible.append((0,1))
            elif dx<0: possible.append((0,-1))
            safe = None
            for d in possible:
                nh = (head[0]+d[0], head[1]+d[1])
                if nh not in snake and 0<nh[0]<h-1 and 0<nh[1]<w-1: safe=d; break
            if not safe:
                nh = (head[0]+dir[0], head[1]+dir[1])
                if nh not in snake and 0<nh[0]<h-1 and 0<nh[1]<w-1: safe=dir
                else:
                    for d in [(1,0),(-1,0),(0,1),(0,-1)]:
                        nh = (head[0]+d[0], head[1]+d[1])
                        if nh not in snake and 0<nh[0]<h-1 and 0<nh[1]<w-1: safe=d; break
            if safe: dir = safe
            else: break
        head = snake[0]; nh = (head[0]+dir[0], head[1]+dir[1])
        if nh in snake or nh[0]<=0 or nh[0]>=h-1 or nh[1]<=0 or nh[1]>=w-1: break
        snake.insert(0, nh)
        if nh == food: score+=1; food=place_food()
        else: snake.pop()
        s.clear()
        for x in range(w):
            s.addch(0,x,'#'); s.addch(h-1,x,'#')
        for y in range(h):
            s.addch(y,0,'#'); s.addch(y,w-1,'#')
        s.addch(food[0],food[1],'@')
        for i,seg in enumerate(snake):
            s.addch(seg[0], seg[1], 'O' if i==0 else 'o')
        s.addstr(0,2,f"Score: {score}")
        s.refresh()
        if demo: curses.napms(150)
    s.clear(); s.addstr(h//2,w//2-5,"Game Over!"); s.refresh(); s.nodelay(0); s.getch()

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except:
        sys.exit(0)
