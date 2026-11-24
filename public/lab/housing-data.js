const release=/^[a-f0-9]{20}$/;
export const cad=new Intl.NumberFormat("en-CA",{style:"currency",currency:"CAD",maximumFractionDigits:0});

export async function housingRelease(folder,key,json,pinned){
  let version=pinned;
  if(!version){
    const response=await fetch(folder+key+".json");
    if(response.status===404)return null;
    if(!response.ok)throw Error("The housing estimates are unavailable.");
    ({version}=await response.json());
  }
  if(!release.test(version))throw Error("Invalid housing release.");
  const base=folder+version+"/";
  return {version,base,report:await json(base+"report.json")};
}
