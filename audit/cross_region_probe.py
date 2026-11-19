"""Hold the visitor, model and program constant; vary just the representation of the geography slot."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent import Agent,apply_constraints
from planning import new_contract,Invalid
from feedback import PROMPT

def run(out):
    question=json.loads((ROOT/'audit/benchmark-1118-regression/eval_agent.json').read_text(encoding='utf8'))[0]['input']
    rows=[]
    with tempfile.TemporaryDirectory() as d:
        for target,value in [('汉口',''),('','汉口老建筑'),('','汉口')]:
            agent=Agent(str(Path(d)/'probe.sqlite'))
            ask=agent.model.ask
            def exercise(instruction,payload,*args,**kwargs):
                result=ask(instruction,payload,*args,**kwargs)
                if instruction==PROMPT:
                    result['操作']=[x for x in result['操作'] if x['动作']!='限定区域']
                    result['操作'].append({'动作':'限定区域','原文片段编号':2,'站点对象或空':target,'新值':value})
                return result
            agent.model.ask=exercise
            try:
                apply_constraints(new_contract(),{'set':{'regions':[value]}})
                direct='accepted'
            except Invalid as e:
                direct=str(e)
            spec=agent.understand(question,{'days':{},'facts':[],'turns':[]})
            rows.append({'controlled_fields':[target,value],'unmapped_validator':direct,'normalized':spec,
                         'passed':spec['mode']=='plan' and spec['days'][0]['set']['regions']==['汉口']})
            out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':run(Path(sys.argv[1]))
