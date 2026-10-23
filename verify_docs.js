// verify_docs.js — 校验生成后的工作台：每个节点都挂到文档、且文档能渲染
// 用法：node verify_docs.js <生成的工作台.html>
// 运行时校验：抽出 mdToHtml / docHeadings / docMapHtml，对 CONFIG.docs 每份文档实跑。
// node --check 只查语法，查不出锚点错位、代码块吞正文、节点漏挂文档等问题。
const fs = require('fs');

const F = process.argv[2];
if (!F) { console.error('用法: node verify_docs.js <工作台.html>'); process.exit(2); }
const html = fs.readFileSync(F, 'utf8');

const i0 = html.indexOf('const CONFIG = ') + 'const CONFIG = '.length;
const i1 = html.indexOf('const STORE_KEY');
let cfg;
try { cfg = JSON.parse(html.slice(i0, i1).replace(/;\s*$/, '')); }
catch (e) { console.log('CONFIG PARSE FAIL: ' + e.message); process.exit(1); }

const s0 = html.indexOf('function mdInline(');
const s1 = html.indexOf('function openDoc(');
if (s0 < 0 || s1 < 0) { console.log('FUNC EXTRACT FAIL（模板结构变了？）'); process.exit(1); }
const escapeHtml = s => (s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const M = new Function('escapeHtml', html.slice(s0, s1) + '\nreturn {mdToHtml,docHeadings,docMapHtml};')(escapeHtml);

const docs = cfg.docs || {};
const used = {};       // docKey -> node count
let nodes = 0, noDoc = 0;

cfg.seed.projects.forEach(function (p) {
  (function walk(n) {
    nodes++;
    const k = n.docKey;
    if (!k || !docs[k]) { noDoc++; console.log('NODOC ' + n.title); }
    else used[k] = (used[k] || 0) + 1;
    (n.children || []).forEach(walk);
  })(p.root);
});

let badDoc = 0;
Object.keys(used).forEach(function (k) {
  const d = docs[k];
  try {
    const hs = M.docHeadings(d.text);
    const raw = M.mdToHtml(d.text);
    const map = M.docMapHtml(d.text, k);
    const rawIds = (raw.match(/id="dh\d+"/g) || []).length;
    const mapIds = (map.match(/data-h="dh\d+"/g) || []).length;
    const textLen = raw.replace(/<[^>]+>/g, '').replace(/\s/g, '').length;
    const ok = hs.length > 0 && rawIds === hs.length && mapIds === hs.length && textLen > 40;
    if (!ok) badDoc++;
    console.log((ok ? 'OK   ' : 'FAIL ') + '[' + d.kind + '] ' + k +
      ' | 节点 ' + used[k] + ' | 标题 ' + hs.length +
      ' | raw ' + rawIds + ' | map ' + mapIds +
      ' | 覆盖 ' + Math.round(textLen / Math.max(1, d.text.replace(/\s/g, '').length) * 100) + '%' +
      ' | ' + d.text.length + ' 字');
  } catch (e) {
    badDoc++;
    console.log('THROW ' + k + ' :: ' + e.message);
  }
});

const has = k => html.indexOf(k) >= 0;
console.log('---');
console.log('nodes=' + nodes + ' docs=' + Object.keys(used).length + ' noDoc=' + noDoc + ' badDoc=' + badDoc);
console.log('docModal=' + has('id="docModal"') + ' docTabs=' + has('id="docTabs"') +
  ' btnDoc=' + has('id="btnDoc"') + ' docflag=' + has('class="docflag"'));
process.exit((noDoc || badDoc) ? 1 : 0);
