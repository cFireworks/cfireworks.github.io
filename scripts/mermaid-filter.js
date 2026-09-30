/**
 * Hexo filter to convert mermaid code blocks to proper format for NexT theme
 * NexT expects: <pre><code class="mermaid">...</code></pre>
 */

'use strict';

hexo.extend.filter.register('after_post_render', function(data) {
  // Case 1: Handle <pre class="mermaid">...</pre> (线上实际格式)
  // 这是当前线上的实际 HTML 格式，必须先处理
  data.content = data.content.replace(/<pre class="mermaid">([\s\S]*?)<\/pre>/g, function(match, codeContent) {
    // 解码常见 HTML 实体
    const cleanContent = codeContent
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#123;/g, '{')
      .replace(/&#125;/g, '}')
      .trim();
    
    // 转换为 NexT 期望的格式
    return `<pre><code class="mermaid">\n${cleanContent}\n</code></pre>`;
  });

  // Case 2: Handle <figure class="highlight plaintext/mermaid"> (兜底处理)
  // 如果 markdown 渲染器生成了代码高亮块，也要处理
  const mermaidRegex = /<figure class="highlight (?:plaintext|mermaid)"><table><tr><td class="gutter">.*?<\/td><td class="code"><pre>([\s\S]*?)<\/pre><\/td><\/tr><\/table><\/figure>/g;
  
  data.content = data.content.replace(mermaidRegex, function(match, codeContent) {
    // 提取代码行
    const lines = codeContent.match(/<span class="line">(.*?)<\/span><br>/g);
    if (!lines) return match;
    
    // 检查是否为 mermaid 代码（以关键词开头）
    const firstLine = lines[0].replace(/<span class="line">|<\/span><br>/g, '').trim();
    const mermaidKeywords = ['graph', 'flowchart', 'sequenceDiagram', 'classDiagram', 'stateDiagram', 'erDiagram', 'gantt', 'pie', 'journey'];
    
    const isMermaid = mermaidKeywords.some(keyword => firstLine.startsWith(keyword));
    if (!isMermaid) return match;
    
    // 提取并清理代码
    let mermaidCode = lines.map(line => {
      return line.replace(/<span class="line">|<\/span><br>/g, '')
                 .replace(/&lt;/g, '<')
                 .replace(/&gt;/g, '>')
                 .replace(/&amp;/g, '&')
                 .replace(/&quot;/g, '"')
                 .replace(/&#39;/g, "'")
                 .replace(/&#123;/g, '{')
                 .replace(/&#125;/g, '}');
    }).join('\n');
    
    // 返回正确格式
    return `<pre><code class="mermaid">\n${mermaidCode}\n</code></pre>`;
  });
  
  return data;
});
