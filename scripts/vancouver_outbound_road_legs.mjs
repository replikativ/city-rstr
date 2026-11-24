// Locate every recorded leg touching the external paid-work slots on one resident's day.
import {readFileSync,writeSync} from "node:fs";
import {join} from "node:path";

const [root,jointId]=process.argv.slice(2);
const transit=process.argv.includes("--transit");
const read=file=>JSON.parse(readFileSync(join(root,file)));
const joint=read(`joint-weekday/${jointId}/report.json`);
const dayRoot=`cityday/${joint.versions.day}/`, atlasRoot=`atlas/${joint.versions.atlas}/`;
const outbound=`outbound/${joint.workplaces.outbound}/`;
const day=read(dayRoot+"day.json"), atlas=read(atlasRoot+"atlas.json"), report=read(outbound+"report.json");
const shards=read(outbound+"assignments.json");
if(report.day!==joint.versions.day||report.atlas!==joint.versions.atlas||shards.length!==day.das.length)
  throw Error("External workplace assignments use a different resident roster.");

const schedules=day.templates.map(({parts},tpl)=>{
  const paid=new Set(report.slots[tpl]);
  const work=parts.filter(([,,mode,a])=>mode==="stop"&&paid.has(a)).map(([,,,a])=>a);
  const all=parts.flatMap(([start,duration,mode,a,b])=>{
    if(mode==="stop"||(!paid.has(a)&&!paid.has(b)))return [];
    const modes=new Set(atlas.templates[tpl].episodes.filter(([s])=>start<=s&&s<start+duration).map(e=>e[3]));
    const driving=modes.size===1&&modes.has("car-driver");
    const supported=modes.size===1&&(driving||modes.has("car-passenger"));
    const from=paid.has(a),to=paid.has(b);
    const pureTransit=modes.has("transit")&&[...modes].every(m=>m==="transit"||m==="walk");
    return [[start,duration,from===to?-1:from?b:a,from,transit?modes.has("transit"):driving,transit?pureTransit:supported]];
  });
  const absent=parts.some(([,,mode,a],j)=> j>0&&mode==="stop"&&parts[j-1][2]==="stop"&&paid.has(a)!==paid.has(parts[j-1][3]));
  return {work,all,absent};
});

for(const [d,da] of day.das.entries()){
  if(!shards[d].length)continue;
  const {people}=read(atlasRoot+da+".json"), {plans}=read(dayRoot+da+".json");
  if(people.length!==plans.length)throw Error("External trips and resident locations disagree at "+da);
  const lines=[];
  for(const [i,destination] of shards[d]){
    const {work,all,absent}=schedules[people[i][7]];
    if(!work.length)continue;
    const legs=all.map(([s,n,slot,from,driving,supported])=>[s,n,plans[i][slot]??-1,from,driving,supported]);
    lines.push(JSON.stringify([d,i,report.destinations[destination],work,legs,absent]));
  }
  if(lines.length)writeSync(1,lines.join("\n")+"\n");
}
