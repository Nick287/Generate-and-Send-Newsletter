import requests
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
import html.parser
import re
import os # 导入 os 模块以读取环境变量
from emailsender import EmailSender


from openai import AzureOpenAI

# --- AI Client Initialization ---
def get_ai_client():
    """
    初始化并返回一个 Azure OpenAI 客户端。
    它会从环境变量 "AZURE_OPENAI_KEY" 中读取 API 密钥。
    """
    try:
        # 从环境变量中获取 API Key
        api_key = os.getenv("AZURE_OPENAI_KEY")
        if not api_key:
            raise ValueError("环境变量 AZURE_OPENAI_KEY 未设置!")

        client = AzureOpenAI(
            api_key=api_key,
            api_version="2025-04-01-preview",
            azure_endpoint="https://bowan-mk2l0mhg-eastus2.cognitiveservices.azure.com/"
        )
        return client
    except Exception as e:
        raise RuntimeError(f"初始化 Azure AI Client 时发生错误: {e}") from e

class HTMLToMarkdownParser(html.parser.HTMLParser):
    """
    一个使用标准库 html.parser 将 HTML 转换为 Markdown 的解析器。
    """
    def __init__(self):
        super().__init__()
        self.result = []
        self.current_href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p':
            self.result.append('\n\n')
        elif tag in ['strong', 'b']:
            self.result.append('**')
        elif tag in ['em', 'i']:
            self.result.append('*')
        elif tag == 'a':
            self.current_href = attrs.get('href', '')
            self.result.append('[')
        elif tag == 'h1':
            self.result.append('\n\n# ')
        elif tag == 'h2':
            self.result.append('\n\n## ')
        elif tag == 'h3':
            self.result.append('\n\n### ')
        elif tag == 'li':
            self.result.append('\n* ')
        elif tag == 'br':
            self.result.append('  \n') # Markdown的换行
        elif tag == 'img':
            alt = attrs.get('alt', '')
            src = attrs.get('src', '')
            self.result.append(f'![{alt}]({src})')

    def handle_endtag(self, tag):
        if tag in ['strong', 'b']:
            self.result.append('**')
        elif tag in ['em', 'i']:
            self.result.append('*')
        elif tag == 'a':
            if self.current_href:
                self.result.append(f']({self.current_href})')
                self.current_href = None

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.result.append(text)

    def get_markdown(self):
        full_text = "".join(self.result).strip()
        return re.sub(r'\n{3,}', '\n\n', full_text)

def html_to_markdown_stdlib(html_string: str) -> str:
    if not html_string:
        return ""
    parser = HTMLToMarkdownParser()
    parser.feed(html_string)
    return parser.get_markdown()

def etree_to_dict(t):
    d = {t.tag: {} if t.attrib else None}
    children = list(t)
    if children:
        dd = defaultdict(list)
        for dc in map(etree_to_dict, children):
            for k, v in dc.items():
                dd[k].append(v)
        d = {t.tag: {k: v[0] if len(v) == 1 else v for k, v in dd.items()}}
    if t.attrib:
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.items())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
                d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d

def parse_xml_without_deps(xml_string: str) -> dict:
    try:
        root = ET.fromstring(xml_string)
        return etree_to_dict(root)
    except ET.ParseError as e:
        print(f"XML 解析错误: {e}")
        return {"error": "Invalid XML format"}
    except Exception as e:
        print(f"发生未知错误: {e}")
        return {"error": str(e)}

def extract_markdown_sections(markdown_text: str) -> dict:
    sections = {'header': '', 'twitter_recap': '', 'reddit_recap': ''}
    parts = re.split(r'(\n#\s.+)', markdown_text)
    if parts:
        sections['header'] = parts[0].strip()
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        content = parts[i+1].strip() if (i + 1) < len(parts) else ''
        if 'AI Twitter Recap' in heading:
            sections['twitter_recap'] = content
        elif 'AI Reddit Recap' in heading:
            sections['reddit_recap'] = content
    return sections

def markdown_to_html(md_text: str) -> str:
    """
    将基本的 Markdown 文本转换为 HTML。
    此版本能正确处理段落、列表、标题(##, ###)、图片和分隔线。
    """
    if not md_text:
        return ""

    def process_inline(text: str) -> str:
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1" style="max-width: 100%; height: auto; border-radius: 8px; margin: 1em 0;">', text)
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" style="color: #61dafb;">\1</a>', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
        return text

    html_output = []
    lines = md_text.strip().split('\n')
    current_paragraph_lines = []
    in_list = False

    def flush_paragraph():
        nonlocal current_paragraph_lines
        if current_paragraph_lines:
            para_text = ' '.join(current_paragraph_lines).replace('  ', '<br>')
            html_output.append(f'<p>{process_inline(para_text)}</p>')
            current_paragraph_lines = []

    for line in lines:
        stripped_line = line.strip()

        if not stripped_line:
            flush_paragraph()
            if in_list:
                html_output.append('</ul>')
                in_list = False
            continue

        heading_match = re.match(r'^(#{1,3})\s+(.*)', stripped_line)
        if heading_match:
            flush_paragraph()
            if in_list:
                html_output.append('</ul>'); in_list = False
            
            level = len(heading_match.group(1))
            content = heading_match.group(2)
            html_level = level + 1 # 映射到 h2, h3, h4
            html_output.append(f'<h{html_level}>{process_inline(content)}</h{html_level}>')
            continue

        if stripped_line.startswith('* '):
            flush_paragraph()
            if not in_list:
                html_output.append('<ul>'); in_list = True
            item_content = stripped_line.lstrip('* ').strip()
            html_output.append(f'<li>{process_inline(item_content)}</li>')
        
        elif re.fullmatch(r'---+|\*\*\*+|___+', stripped_line):
            flush_paragraph()
            if in_list:
                html_output.append('</ul>'); in_list = False
            html_output.append('<hr style="border: 0; border-top: 1px solid #444; margin: 2em 0;">')
        
        else:
            if in_list:
                html_output.append('</ul>'); in_list = False
            current_paragraph_lines.append(line)

    flush_paragraph()
    if in_list:
        html_output.append('</ul>')

    return '\n'.join(html_output)

def translate_text(text_to_translate: str, target_language: str = "中文", system_prompt_override: str = None) -> str:
    """
    使用 Azure OpenAI 服务进行翻译。可以接受一个可选的 system_prompt_override 来改变AI的角色。
    """
    if not text_to_translate or not text_to_translate.strip():
        return ""
    
    print(f"--- 正在处理AI任务: {text_to_translate[:30]}... ---")
    
    # 默认的系统指令是直接翻译
    system_prompt = system_prompt_override if system_prompt_override else f"You are a direct translation engine. Your sole task is to translate the user's text into {target_language}. Provide only the translated text, without any additional comments, explanations, or conversational phrases."
    
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_to_translate}
    ]
    try:
        ai_client = get_ai_client()
        response = ai_client.chat.completions.create(
            model="gpt-5.4", 
            messages=messages,
            # max_tokens=4096,
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"调用 AI 时发生错误: {e}")
        return f"[AI处理失败] {text_to_translate}"

def create_newsletter_html(translated_title: str, translated_header: str, translated_twitter: str, translated_reddit: str) -> str:
    header_html = markdown_to_html(translated_header)
    twitter_html = markdown_to_html(translated_twitter)
    reddit_html = markdown_to_html(translated_reddit)

    twitter_section_html = f'<div class="section"><h2>AI Twitter Recap (摘要)</h2>{twitter_html}</div>' if twitter_html else ""
    reddit_section_html = f'<div class="section"><h2>AI Reddit Recap (摘要)</h2>{reddit_html}</div>' if reddit_html else ""

    return f"""
    <!DOCTYPE html>
    <html lang="zh">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{translated_title}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
            body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 0; background-color: #121212; color: #e0e0e0; }}
            .container {{ max-width: 680px; margin: 40px auto; background-color: #1e1e1e; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); border: 1px solid #333; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%); color: #ffffff; padding: 40px; text-align: center; border-bottom: 1px solid #333; }}
            .header h1 {{ margin: 0; font-size: 28px; font-weight: 700; letter-spacing: 1px; }}
            .content {{ padding: 30px 40px; line-height: 1.7; }}
            .section {{ margin-bottom: 25px; padding-bottom: 25px; border-bottom: 1px solid #333; }}
            .section:last-child {{ border-bottom: none; margin-bottom: 0; padding-bottom: 0; }}
            h2 {{ color: #61dafb; font-size: 22px; border-bottom: 2px solid #61dafb; padding-bottom: 10px; margin-bottom: 20px; }}
            h3 {{ color: #e0e0e0; font-size: 19px; margin-top: 24px; margin-bottom: 12px; border-bottom: 1px solid #444; padding-bottom: 8px; }}
            h4 {{ color: #bbbbbb; font-size: 16px; font-weight: bold; margin-top: 20px; margin-bottom: 10px; }}
            p {{ margin: 0 0 1em 0; }}
            ul {{ padding-left: 20px; margin: 0; }}
            li {{ margin-bottom: 10px; }}
            a {{ color: #61dafb; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .footer {{ background-color: #1a1a1a; color: #777; text-align: center; padding: 20px; font-size: 12px; border-top: 1px solid #333; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h1>{translated_title}</h1></div>
            <div class="content">
                <div class="section"><h2>导言</h2>{header_html}</div>
                {twitter_section_html}
                {reddit_section_html}
            </div>
            <div class="footer"><p>这是一封由AI自动生成的新闻简报。</p></div>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    rss_url = "https://news.smol.ai/rss.xml"
    try:
        # 添加 30 秒超时以防止网络请求在 Actions 中卡住
        response = requests.get(rss_url, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        xml_content = response.text
    except requests.exceptions.RequestException as e:
        print(f"获取 RSS 源失败: {e}")
        xml_content = None

    if xml_content:
        py_dictionary = parse_xml_without_deps(xml_content)
        
        script_dir = os.path.dirname(os.path.abspath(__file__))

        try:
            articles_list = py_dictionary.get('rss', {}).get('channel', {}).get('item', [])
            if not isinstance(articles_list, list): articles_list = [articles_list]

            article = articles_list[0] if articles_list else None
            
            if article:
                title = article.get('title', '无标题')
                description = article.get('description', '无描述')
                
                content_key = '{http://purl.org/rss/1.0/modules/content/}encoded'
                content_html = article.get(content_key, '<p>无内容。</p>')

                markdown_output = html_to_markdown_stdlib(content_html)
                extracted_sections = extract_markdown_sections(markdown_output)
                
                # 从 header 中移除广告
                header_content = extracted_sections.get('header', '')
                ad_text = "See https://news.smol.ai/ for the full news breakdowns and give us feedback on @smol_ai!"
                cleaned_header = header_content.replace(ad_text, '').strip()

                # 根据标题决定导言内容和翻译方式
                if title.strip().lower() == "not much happened today":
                    header_to_translate = description
                    # 使用特殊的AI指令来生成一个更合适的标题
                    title_prompt_override = "You are a creative editor for an AI newsletter. Your task is to craft an engaging title in Chinese based on the user's input, which indicates a slow news day. Provide only the title text."
                    translated_title = translate_text("今日AI圈无大事发生", system_prompt_override=title_prompt_override)
                else:
                    header_to_translate = cleaned_header
                    translated_title = translate_text(title)

                # 翻译其他部分
                translated_header = translate_text(header_to_translate)
                translated_twitter = translate_text(extracted_sections.get('twitter_recap', ''))
                translated_reddit = translate_text(extracted_sections.get('reddit_recap', ''))
                
                newsletter_html = create_newsletter_html(translated_title, translated_header, translated_twitter, translated_reddit)

                SENDER_USERNAME =  os.getenv("PRO_MAIL_USERNAME")
                SENDER_PASSWORD =  os.getenv("PRO_MAIL_PASSWORD")
                SMTP_HOST = "smtp.qiye.aliyun.com"
                SMTP_PORT = 465 # or 465 for SSL, 587 for TLS

                # Initialize the sender
                # For non-SSL on port 25 with STARTTLS
                email_sender = EmailSender(
                    smtp_host=SMTP_HOST,
                    smtp_port=SMTP_PORT,
                    username=SENDER_USERNAME,
                    password=SENDER_PASSWORD,
                    # use_ssl=False,
                    # use_tls=True,
                    use_ssl=True,
                    use_tls=False,
                    max_retries=3,
                    retry_delay=10
                )

                # --- Send an HTML email from a string ---
                print("--- Sending HTML Email from String ---")
                success_html_string = email_sender.send_email(
                    to_addrs=["bo.wang@comlan.com","edward@playpro.cn"],
                    subject=translated_title,
                    from_alias="PLAYPRO AI",
                    body_html=newsletter_html
                )
                print(f"HTML (from string) email sent successfully: {success_html_string}\n")

                # safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '_')).rstrip()
                # html_filename = os.path.join(script_dir, f"新闻简报_{safe_title}.html")
                # subject_filename = os.path.join(script_dir, "subject.txt")

                # try:
                #     with open(html_filename, 'w', encoding='utf-8') as f:
                #         f.write(newsletter_html)
                #     print(f"成功将 HTML 新闻简报写入文件: {html_filename}")

                #     with open(subject_filename, 'w', encoding='utf-8') as f:
                #         f.write(translated_title)
                #     print(f"成功将邮件主题写入文件: {subject_filename}")
                # except IOError as e:
                #     print(f"写入文件时出错: {e}")
            else:
                print("RSS 源中没有找到任何文章。")

        except (KeyError, TypeError) as e:
            print(f"提取数据时出错：请检查 XML 结构是否正确。错误: {e}")
