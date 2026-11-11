const token=new URLSearchParams(location.hash.slice(1)).get('token')||sessionStorage.getItem('app-token');
if(token)sessionStorage.setItem('app-token',token);
if(location.hash)history.replaceState(null,'',location.pathname+location.search);
export async function api(path,body){
 const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'X-App-Token':token||'',...(body===undefined?{}:{'Content-Type':'application/json'})},...(body===undefined?{}:{body:JSON.stringify(body)})});
 if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('检测服务暂时没有响应，请稍后重试。');
 const data=await response.json();if(!response.ok)throw new Error(data.error||'操作未完成');return data;
}
