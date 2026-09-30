/**
 * Hexo filter to convert mermaid code blocks to proper format for NexT theme
 * NexT expects: <pre><code class="mermaid">...</code></pre>
 */

'use strict';

hexo.extend.filter.register('after_post_render', function(data) {
  // Match ```mermaid code blocks that were rendered as <figure class="highlight plaintext">
  // or <figure class="highlight mermaid">
  const mermaidRegex = /<figure class="highlight (?:plaintext|mermaid)"><table><tr><td class="gutter">.*?<\/td><td class="code"><pre>([\s\S]*?)<\/pre><\/td><\/tr><\/table><\/figure>/g;
  
  data.content = data.content.replace(mermaidRegex, function(match, codeContent) {
    // Extract the actual mermaid code from the HTML
    const lines = codeContent.match(/<span class="line">(.*?)<\/span><br>/g);
    if (!lines) return match;
    
    // Check if this looks like mermaid code (starts with graph, flowchart, sequenceDiagram, etc.)
    const firstLine = lines[0].replace(/<span class="line">|<\/span><br>/g, '').trim();
    const mermaidKeywords = ['graph', 'flowchart', 'sequenceDiagram', 'classDiagram', 'stateDiagram', 'erDiagram', 'gantt', 'pie', 'journey'];
    
    const isMermaid = mermaidKeywords.some(keyword => firstLine.startsWith(keyword));
    if (!isMermaid) return match;
    
    // Extract clean mermaid code
    let mermaidCode = lines.map(line => {
      return line.replace(/<span class="line">|<\/span><br>/g, '')
                 .replace(/&lt;/g, '<')
                 .replace(/&gt;/g, '>')
                 .replace(/&amp;/g, '&')
                 .replace(/&quot;/g, '"')
                 .replace(/&#123;/g, '{')
                 .replace(/&#125;/g, '}');
    }).join('\n');
    
    // Return the proper format for NexT theme
    return `<pre><code class="mermaid">\n${mermaidCode}\n</code></pre>`;
  });
  
  return data;
});
