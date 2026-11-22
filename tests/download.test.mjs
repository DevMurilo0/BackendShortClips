import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHandler} from '../api/download.js';
const pathname='shortforge/jobs/2026-11/'+ 'a'.repeat(32)+'/output/short_01.mp4';
const key='x'.repeat(40);
process.env.SHORTFORGE_ENGINE='sandbox';
process.env.SHORTFORGE_PUBLIC_ACCESS_KEY=key;
function fixture(overrides={}){
  const state={status:'completed',expires_at:new Date(Date.now()+60000).toISOString(),clips:[{status:'ready',blob_path:pathname}],...overrides};
  const calls=[];
  const storage={get:async()=>({statusCode:200,stream:new Response(JSON.stringify(state)).body}),head:async()=>({}),
    issueSignedToken:async opts=>{calls.push(opts);return {}},presignUrl:async(_t,opts)=>{calls.push(opts);return {presignedUrl:'https://private.example/signed'}}};
  const res={statusCode:200,setHeader(){},status(n){this.statusCode=n;return this},json(body){this.body=body;return this},end(){return this}};
  const req={method:'GET',headers:{authorization:'Bearer '+key},query:{pathname}};
  return {state,calls,storage,res,req};
}
test('signed read checks job membership and caps URL to job expiration',async()=>{
  const f=fixture();await createHandler(f.storage)(f.req,f.res);
  assert.equal(f.res.statusCode,200);assert.equal(f.calls[0].validUntil,Date.parse(f.state.expires_at));assert.equal(f.calls[0].pathname,pathname);
});
for(const [name,mutate,status] of [
  ['missing auth',f=>delete f.req.headers.authorization,401],
  ['wrong origin',f=>f.req.headers.origin='https://evil.test',403],
  ['traversal',f=>f.req.query.pathname='../.env',400],
  ['unknown artifact',f=>f.state.clips=[],404],
  ['expired',f=>f.state.expires_at='2020-01-01T00:00:00Z',410],
  ['cancelled',f=>f.state.status='cancelled',409],
  ['uploading',f=>f.state.status='running',409],
  ['Blob failure',f=>f.storage.get=async()=>{throw Error('storage unavailable')},503]
])test(name,async()=>{const f=fixture();mutate(f);await createHandler(f.storage)(f.req,f.res);assert.equal(f.res.statusCode,status);assert.equal(f.calls.length,0)});
