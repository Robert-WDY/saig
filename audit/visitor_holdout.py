"""Fresh visitor situations for the post-repair HTTP acceptance run."""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from visitor_dialogues import run, write

inputs = {
    "editor": [
        "我在给校报写稿子。有人把武汉江岸的数命社区写成了新荣社区，还写学员只上理论课。请逐项核实，给我能直接核对的依据。",
        "稿子里还想加一句：报名线上赛必须先建自己的网站。这个说法准确吗？如果不准确，实际必交的两样材料是什么？",
    ],
    "pickup": [
        "我准备从江汉路出发看一处老建筑，黎黄陂路一定要去。下午两点要到汉口站接朋友，我想提前二十分钟等他。请给我一张上午九点开始的卡。",
        "对方发来消息，火车晚半小时，还是提前二十分钟等他。只给备选，我先看一眼。",
        "先别采用。正式行程接人那天的终点是哪里？",
    ],
}
if __name__=="__main__":
    out=Path(sys.argv[1])
    out.mkdir(parents=True,exist_ok=False)
    write(out/"manifest.json",{"inputs":inputs,"repeats":1,"workers":2})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda case:run(case,out,"http://127.0.0.1:18943",1,inputs),inputs))
