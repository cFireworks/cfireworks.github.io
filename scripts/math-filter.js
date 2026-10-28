/**
 * 在 Markdown 渲染前抽出公式，生成后再写回 KaTeX HTML。
 *
 * hexo-renderer-marked 会把 LaTeX 里的 \_、\{、\( 当成转义，下划线还会变成斜体，
 * 所以只在 NexT 里打开前端 MathJax 时，静态 HTML 里仍是被拆碎的 $$ 原文。
 * NexT 8.29 的 KaTeX 路径预期页面里已经是 KaTeX HTML，主题只提供同版本 CSS。
 *
 * 不启用主题 MathJax：它的 mathjax.js 写死了 $...$ 行内定界符，会把 $0.07 这类价格吃掉。
 * 单美元只在看起来像公式时才渲染（含 \ _ ^，或 s、(r,c)、O(whn) 这种短式）。
 */

'use strict';

const katex = require('katex');

const TOKEN_RE = /HEXOMATHTOKEN(\d+)END/g;
const store = new Map();
let seq = 0;

function stash(html) {
  const id = seq++;
  store.set(id, html);
  return `HEXOMATHTOKEN${id}END`;
}

function prepareTex(tex, displayMode) {
  // Markdown 硬换行会吃掉一行末尾的一个反斜杠，源码里常见 `\↵` 而不是 `\\`。
  let src = tex.replace(/(?<!\\)\\(?=\s*\n)/g, '\\\\').trim();
  if (displayMode && /\\\\/.test(src) && !/\\begin\{/.test(src)) {
    src = `\\begin{aligned}${src}\\end{aligned}`;
  }
  return src;
}

function renderTex(tex, displayMode) {
  const src = prepareTex(tex, displayMode);
  const html = katex.renderToString(src, {
    displayMode,
    throwOnError: false,
    strict: 'ignore',
    output: 'html',
    trust: false
  });
  if (html.includes('katex-error') && typeof hexo !== 'undefined') {
    hexo.log.warn('[math] KaTeX 无法渲染: %s', src.replace(/\s+/g, ' ').slice(0, 200));
  }
  return html;
}

function isMathDollar(inner) {
  if (!inner || inner.length > 300) return false;
  if (/[\u4e00-\u9fff]/.test(inner)) return false;
  if (/[`<>]/.test(inner)) return false;
  if (/^\s|\s$/.test(inner)) return false;
  // $0.07、$4,644 这类价格。$2 \times 2$ 含命令，仍是公式。
  if (/^\d/.test(inner) && !/[\\_^]/.test(inner)) return false;
  if (/[\\_^]/.test(inner)) return true;
  // ${VERSION} 不是公式。花括号必须和 TeX 命令或上下标一起出现。
  if (/[{}]/.test(inner)) return false;
  return /^[A-Za-z][A-Za-z0-9]*$/.test(inner)
    || /^\([^()\n]+\)$/.test(inner)
    || /^[A-Za-z][A-Za-z0-9]*\([^()\n]*\)$/.test(inner);
}

function replaceSingleDollars(text) {
  let out = '';
  let i = 0;
  while (i < text.length) {
    const open = text[i] === '$' && text[i - 1] !== '\\' && text[i + 1] !== '$';
    if (!open) {
      out += text[i];
      i += 1;
      continue;
    }
    let close = -1;
    for (let j = i + 1; j < text.length; j += 1) {
      if (text[j] === '\n') break;
      if (text[j] === '$' && text[j - 1] !== '\\') {
        close = j;
        break;
      }
    }
    if (close === -1) {
      out += text.slice(i);
      break;
    }
    const inner = text.slice(i + 1, close);
    if (!isMathDollar(inner)) {
      // 只吃掉这个开美元，让下一个 $ 还能当公式开头（价格后面紧跟 $C_{\text{idle}}$）。
      out += text[i];
      i += 1;
      continue;
    }
    out += stash(renderTex(inner, false));
    i = close + 1;
  }
  return out;
}

function replaceMath(text) {
  let src = text;
  src = src.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => stash(renderTex(tex, true)));
  src = src.replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => stash(renderTex(tex, true)));
  src = src.replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => stash(renderTex(tex, false)));
  src = replaceSingleDollars(src);
  return src;
}

function protectAndReplace(content) {
  const re = /<hexoPostRenderCodeBlock>[\s\S]*?<\/hexoPostRenderCodeBlock>|```[\s\S]*?```|~~~[\s\S]*?~~~|`+[^`\n]*`+/g;
  let out = '';
  let last = 0;
  for (const match of content.matchAll(re)) {
    out += replaceMath(content.slice(last, match.index));
    out += match[0];
    last = match.index + match[0].length;
  }
  out += replaceMath(content.slice(last));
  return out;
}

function restore(content) {
  return content.replace(TOKEN_RE, (match, id) => {
    const html = store.get(Number(id));
    if (html == null) return match;
    store.delete(Number(id));
    return html;
  });
}

if (typeof hexo !== 'undefined') {
  // 先于内置 backtick 代码块过滤器（priority 10）。
  hexo.extend.filter.register('before_post_render', data => {
    if (!data || typeof data.content !== 'string' || !data.content) return data;
    data.content = protectAndReplace(data.content);
    return data;
  }, 9);

  // 先于 excerpt 和 mermaid（priority 10），摘要里的公式同样是 KaTeX HTML。
  hexo.extend.filter.register('after_post_render', data => {
    if (!data || typeof data.content !== 'string') return data;
    data.content = restore(data.content);
    return data;
  }, 1);
}

module.exports = {
  protectAndReplace,
  restore,
  isMathDollar,
  renderTex
};
