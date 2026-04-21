import re
import requests
import xml.etree.ElementTree as ET
from collections import defaultdict
import re
import os

from function.AzureAIClient import AzureAiClient, non_stream_processor
from function.EmailSender import EmailSender
from NewsTemplate.AINewsTemplate import create_newsletter_html

# from markdownify import markdownify as md
import html2text

class RSSProcessor:
    def _etree_to_dict(self, t):
        """
        一个递归函数，将 ElementTree 对象转换为字典。
        关键在于处理重复的标签，将其值放入一个列表中。
        """
        d = {t.tag: {} if t.attrib else None}
        children = list(t)
        if children:
            dd = defaultdict(list)
            for dc in map(self._etree_to_dict, children):
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

    def parse_xml(self, xml_string: str) -> dict:
        """
        主函数，接收 XML 字符串，使用内置库进行解析。
        """
        try:
            root = ET.fromstring(xml_string)
            dict_output = self._etree_to_dict(root)
            return dict_output
        except ET.ParseError as e:
            print(f"XML 解析错误: {e}")
            return {"error": "Invalid XML format"}
        except Exception as e:
            print(f"发生未知错误: {e}")
            return {"error": str(e)}

    def read_feed(self, rss_url: str) -> str:
        """
        使用 requests 获取 RSS 源内容。
        """
        try:
            response = requests.get(rss_url)
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"获取 RSS 源失败: {e}")
            return ""
        
    def extract_markdown_sections(self, markdown_text: str) -> dict:
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

class NewsCollector:

    def get_ai_client(self):
        """
        Initializes and returns an instance of the AzureAiClient.
        """
        AZURE_OPENAI_TOKEN, AZURE_OPENAI_ENDPOINT =  os.getenv("AZURE_OPENAI_TOKEN"),  os.getenv("AZURE_OPENAI_ENDPOINT")

        if not all([AZURE_OPENAI_TOKEN, AZURE_OPENAI_ENDPOINT]) or \
        "YOUR_AZURE" in AZURE_OPENAI_TOKEN:
            raise ValueError("请在 `app_config/keys_config.py` 文件中配置您的 Azure OpenAI 凭据。" )
        
        try:
            client = AzureAiClient(
                api_key=AZURE_OPENAI_TOKEN,
                api_version="2025-01-01-preview",  # Using a stable, recommended API version
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                rest_endpoint=AZURE_OPENAI_ENDPOINT,  # Assuming the same endpoint for REST
            )
            return client
        except Exception as e:
            raise RuntimeError(f"初始化 Azure AI Client 时发生错误: {e}") from e

    def summary_text(self, text_to_summarize: str) -> str:
        """
        使用 Azure OpenAI 服务进行文本总结。
        """
        if not text_to_summarize or not text_to_summarize.strip():
            return ""

        print(f"--- 正在处理AI总结任务: {text_to_summarize[:30]}... ---")

        system_prompt = "You are a helpful assistant that summarizes the user's text into concise key points to a level that high school students can understand. Provide only the summarized text, without any additional comments, explanations, or conversational phrases. the input text is in markdown format, keep the markdown format in your summary, please keep the link for some important reference."
        
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_to_summarize}
        ]
        try:
            ai_client = self.get_ai_client()
            response = ai_client.get_chat_completion(
                model="gpt-5.4", 
                messages=messages,
                # max_tokens=4096,
                temperature=0.3,
                stream=False,  # 非流式响应
            )
            return non_stream_processor(response)
        except Exception as e:
            print(f"调用 AI 时发生错误: {e}")
            return f"[AI处理失败] {text_to_summarize}"

    def remove_ads(self, text: str) -> str:
        """
        使用 AI 大模型移除文本中的广告和推广内容，保留正文。
        """
        if not text or not text.strip():
            return ""

        print(f"--- 正在使用AI移除广告内容 ---")

        system_prompt = (
            "You are a text cleaning assistant. Your task is to remove all advertisements, "
            "promotional content, sponsor messages, calls-to-action (e.g. 'subscribe', 'follow us', "
            "'give us feedback'), and self-promotion from the user's text. "
            "Return ONLY the cleaned text with the original markdown formatting preserved. "
            "Do not add any comments or explanations."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
        try:
            ai_client = self.get_ai_client()
            response = ai_client.get_chat_completion(
                model="gpt-5.4",
                messages=messages,
                temperature=0.1,
                stream=False,
            )
            return non_stream_processor(response)
        except Exception as e:
            print(f"调用 AI 移除广告时发生错误: {e}")
            return text

    def translate_text(self, text_to_translate: str, target_language: str = "中文", system_prompt_override: str = None) -> str:
        """
        使用 Azure OpenAI 服务进行翻译。可以接受一个可选的 system_prompt_override 来改变AI的角色。
        """
        if not text_to_translate or not text_to_translate.strip():
            return ""
        
        print(f"--- 正在处理AI翻译任务: {text_to_translate[:30]}... ---")
        
        # 默认的系统指令是直接翻译
        system_prompt = system_prompt_override if system_prompt_override else f"You are a direct translation engine. Your sole task is to translate the user's text into {target_language}. Provide only the translated text, without any additional comments, explanations, or conversational phrases."
        
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_to_translate}
        ]
        try:
            ai_client = self.get_ai_client()
            response = ai_client.get_chat_completion(
                model="gpt-5.4", 
                messages=messages,
                # max_tokens=4096,
                temperature=0.3,
                stream=False,  # 非流式响应
            )
            return non_stream_processor(response)
        except Exception as e:
            print(f"调用 AI 时发生错误: {e}")
            return f"[AI处理失败] {text_to_translate}"

    def collect_news_job(self, rss_url=None, send_email=True):
        rss_url = rss_url or os.getenv("RSS_URL")
        if not rss_url:
            raise ValueError("RSS_URL is not set in settings.")
        # rss_url = "https://news.smol.ai/rss.xml"

        xml_content = RSSProcessor().read_feed(rss_url)
        if xml_content:
            parsed_dict = RSSProcessor().parse_xml(xml_content)
            try:
                articles_list = parsed_dict.get('rss', {}).get('channel', {}).get('item', [])
                if not isinstance(articles_list, list): articles_list = [articles_list]
                article = articles_list[0] if articles_list else None
                
                if article:
                    title = article.get('title', '无标题')
                    description = article.get('description', '无描述')
                    content_key = '{http://purl.org/rss/1.0/modules/content/}encoded'
                    content_html = article.get(content_key, '<p>无内容。</p>')
                    pubDate = article.get('pubDate', '无发布日期')
                    # content_markdown = md(content_html)
                    h = html2text.HTML2Text()
                    # 可选：进行一些配置
                    # h.ignore_links = True  # 如果你想忽略链接
                    # h.body_width = 0       # 不自动换行
                    # 2. 调用 handle 方法进行转换
                    content_markdown = h.handle(content_html)
                    extracted_sections = RSSProcessor().extract_markdown_sections(content_markdown)

                    header_content = extracted_sections.get('header', '')
                    cleaned_header = self.remove_ads(header_content)

                    # 根据标题决定导言内容和翻译方式
                    if title.strip().lower() == "not much happened today":
                        # header_to_translate = description
                        header_to_translate = cleaned_header
                        # 使用特殊的AI指令来生成一个更合适的标题
                        title_prompt_override = "You are a creative editor for an AI newsletter. Your task is to craft an engaging title in Chinese based on the user's input, which indicates a slow news day. Provide only the title text."
                        translated_title = self.translate_text("今日AI圈无大事发生", system_prompt_override=title_prompt_override)
                    else:
                        header_to_translate = cleaned_header
                        translated_title = self.translate_text(title)

                        # 翻译其他部分
                    translated_header = self.translate_text(header_to_translate)
                    translated_twitter = self.translate_text(self.summary_text(extracted_sections.get('twitter_recap', '')))
                    translated_reddit = self.translate_text(self.summary_text(extracted_sections.get('reddit_recap', '')))
                    newsletter_html = create_newsletter_html(translated_title, translated_header, translated_twitter, translated_reddit)

                    if send_email:
                        self.send_email(translated_title, newsletter_html)

                    return translated_title, newsletter_html
                else:
                    print("RSS 源中没有找到任何文章。")

            except (KeyError, TypeError) as e:
                print(f"提取数据时出错：请检查 XML 结构是否正确。错误: {e}")

    def send_email(self, title: str, html_content: str, is_use_ssl=True ,is_use_tls=False) -> bool:
        # 配置您的 SMTP 服务器信息

        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = os.getenv("SMTP_PORT")
        smtp_user = os.getenv("SENDER_USERNAME")
        smtp_pass = os.getenv("SENDER_PASSWORD")
        to_addrs_str = os.getenv("TO_ADDRS")
        from_alias = os.getenv("FROM_ALIAS")

        if not all([smtp_host, smtp_port, smtp_user, smtp_pass, to_addrs_str]):
            raise ValueError("One or more required SMTP or recipient settings are missing.")
        recipients = [addr.strip() for addr in to_addrs_str.split(',') if addr.strip()]

        # SENDER_USERNAME = os.getenv("SENDER_USERNAME", "your_email@example.com")
        # SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your_password") # It's recommended to use environment variables or a config file
        # SMTP_HOST = os.getenv("SMTP_HOST", "smtp.example.com")
        # SMTP_PORT = int(os.getenv("SMTP_PORT", 465)) # or 465 for SSL, 587 for TLS
    
        # SENDER_USERNAME = "bo.wang@playpro.cn"
        # SENDER_PASSWORD = "" # It's recommended to use environment variables or a config file
        # SMTP_HOST = "smtp.qiye.aliyun.com"
        # SMTP_PORT = 465 # or 465 for SSL, 587 for TLS

        # For non-SSL on port 25 with STARTTLS
        email_sender = EmailSender(
            smtp_host=smtp_host,
            smtp_port=int(smtp_port),
            username=smtp_user,
            password=smtp_pass,
            
            # Comlan
            # use_ssl=False,
            # use_tls=True,

            # Aliyun
            # use_ssl=True,
            # use_tls=False,
            
            use_ssl=is_use_ssl,
            use_tls=is_use_tls,
            
            max_retries=3,
            retry_delay=10
        )

        # --- Send an HTML email from a string ---
        print("--- Sending HTML Email from String ---")
        success_html_string = email_sender.send_email(
            to_addrs=recipients,
            subject=title,
            from_alias=from_alias,
            body_html=html_content
        )
        print(f"HTML (from string) email sent successfully: {success_html_string}\n")
        return True
