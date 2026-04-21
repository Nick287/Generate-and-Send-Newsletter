import markdown

def create_newsletter_html(translated_title: str, translated_header: str, translated_twitter: str, translated_reddit: str) -> str:
    header_html = markdown.markdown(translated_header)
    twitter_html = markdown.markdown(translated_twitter)
    reddit_html = markdown.markdown(translated_reddit)

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
            .container {{ width: 90%; max-width: 1100px; margin: 40px auto; background-color: #1e1e1e; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); border: 1px solid #333; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #2a2a2a 0%, #1a1a1a 100%); color: #ffffff; padding: 40px; text-align: center; border-bottom: 1px solid #333; }}
            .header h1 {{ margin: 0; font-size: 28px; font-weight: 700; letter-spacing: 1px; }}
            .content {{ padding: 30px 40px; line-height: 1.7; }}
            .content img {{ max-width: 100%; height: auto; display: block; margin: 20px auto; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.3); }} /* Added responsive image styles */
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