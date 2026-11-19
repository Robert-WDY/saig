"""Short natural visitor conversations. Freeze inputs before making a live comparison."""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from visitor_dialogues import run,write

VISITS={
    "afternoon":["我们在户部巷吃完午饭，下午三点到五点有空，只想去黄鹤楼，来得及吗？帮我排一下。",
                 "那晚半小时再出发呢？五点还得走，先让我看看。"],
    "pickup":["我住江汉路，上午九点出来，想去黎黄陂路走走。下午两点要到汉口站接人，最好提前二十分钟到，怎么走顺路？",
              "朋友说车晚半小时到。帮我把接人的时间往后挪，还是提前二十分钟到站，其他安排尽量别动。"],
    "community":["周末想去江岸的数命社区看看，具体在哪里？我没做过项目，去了能学些什么？",
                 "我们白天要逛街，晚上八点过去还能进去吗？"],
    "oldtown":["我喜欢老建筑，后面推荐就按这个来。江汉路附近有什么老街值得逛？",
               "刚才说的那些里面，哪一处更适合我？"],
}
if __name__=="__main__":
    folder=Path(sys.argv[1]);folder.mkdir(parents=True,exist_ok=False)
    write(folder/"manifest.json",{"inputs":VISITS,"repeats":1,"workers":2})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda case:run(case,folder,"http://127.0.0.1:18943",1,VISITS),VISITS))
