import os
import sys
import re

# Ensure the root folder of the project is in the Python search path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, KeepTogether
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """Custom Canvas to draw running headers and footers with Page X of Y."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748b"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 11 * 72 - 36, "Novus ADOS — Technical Architecture & Executive System Specification")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(54, 11 * 72 - 42, 8.5 * 72 - 54, 11 * 72 - 42)

        # Footer (all pages)
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.5 * 72 - 54, 36, page_str)
        self.drawString(54, 36, "CONFIDENTIAL — IBM WATSONX HACKATHON ENTERPRISE DEMO")
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(54, 48, 8.5 * 72 - 54, 48)

        self.restoreState()


def build_pdf(md_filepath, pdf_filepath):
    with open(md_filepath, "r", encoding="utf-8") as f:
        md_text = f.read()

    doc = SimpleDocTemplate(
        pdf_filepath,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()

    # Custom Executive Paragraph Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=8
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0284c7'),
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=colors.HexColor('#0f172a'),
        spaceBefore=18,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#1e293b'),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h3_style = ParagraphStyle(
        'Heading3_Custom',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#334155'),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155'),
        spaceAfter=8
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=4
    )

    callout_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#1e293b')
    )

    code_style = ParagraphStyle(
        'CodeBlockText',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#0f172a')
    )

    th_style = ParagraphStyle('TH', fontName='Helvetica-Bold', fontSize=9, leading=11, textColor=colors.white)
    td_style = ParagraphStyle('TD', fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#1e293b'))

    story = []

    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Code Block
        if line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            
            # Chunk code blocks to prevent page height overflow
            chunk_size = 20
            for k in range(0, len(code_lines), chunk_size):
                sub_lines = code_lines[k:k+chunk_size]
                sub_text = "\n".join(sub_lines)
                formatted_code = (
                    sub_text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("\n", "<br/>")
                    .replace(" ", "&nbsp;")
                )
                p_code = Paragraph(formatted_code, code_style)
                t_code = Table([[p_code]], colWidths=[504])
                t_code.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
                    ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
                    ('PADDING', (0,0), (-1,-1), 6),
                ]))
                story.append(Spacer(1, 4))
                story.append(t_code)
                story.append(Spacer(1, 4))
            i += 1
            continue

        # Callout Block (> [!NOTE] / > [!IMPORTANT] / > [!TIP] / > [!CAUTION])
        if line.startswith(">"):
            callout_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                c_line = lines[i].lstrip(">").strip()
                if c_line:
                    callout_lines.append(c_line)
                i += 1
            
            callout_raw = " ".join(callout_lines)
            
            border_color = colors.HexColor("#0284c7")
            bg_color = colors.HexColor("#f0f9ff")
            
            if "[!IMPORTANT]" in callout_raw or "[!CAUTION]" in callout_raw:
                border_color = colors.HexColor("#dc2626")
                bg_color = colors.HexColor("#fef2f2")
            elif "[!TIP]" in callout_raw:
                border_color = colors.HexColor("#16a34a")
                bg_color = colors.HexColor("#f0fdf4")

            clean_text = re.sub(r'\[\!(NOTE|IMPORTANT|TIP|CAUTION)\]', '', callout_raw).strip()
            # bold lead titles
            clean_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', clean_text)
            
            p_call = Paragraph(clean_text, callout_style)
            t_call = Table([[p_call]], colWidths=[504])
            t_call.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), bg_color),
                ('LINELEFT', (0,0), (0,0), 4, border_color),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
                ('PADDING', (0,0), (-1,-1), 10),
            ]))
            story.append(Spacer(1, 6))
            story.append(t_call)
            story.append(Spacer(1, 8))
            continue

        # Tables (lines containing |)
        if "|" in line and i + 1 < len(lines) and "|---" in lines[i+1]:
            table_rows = []
            headers = [c.strip() for c in line.split("|")[1:-1]]
            i += 2 # Skip header & separator
            
            while i < len(lines) and "|" in lines[i]:
                row_cols = [c.strip() for c in lines[i].split("|")[1:-1]]
                table_rows.append(row_cols)
                i += 1

            # Format Table
            table_data = []
            header_cells = [Paragraph(re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', h), th_style) for h in headers]
            table_data.append(header_cells)

            for row in table_rows:
                row_cells = []
                for cell in row:
                    cell_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', cell)
                    cell_formatted = re.sub(r'`(.*?)`', r'<font face="Courier" size="8">\1</font>', cell_formatted)
                    row_cells.append(Paragraph(cell_formatted, td_style))
                table_data.append(row_cells)

            num_cols = len(headers)
            col_w = 504 / num_cols
            t_table = Table(table_data, colWidths=[col_w] * num_cols)
            t_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('TOPPADDING', (0,0), (-1,-1), 6),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')])
            ]))
            story.append(Spacer(1, 6))
            story.append(t_table)
            story.append(Spacer(1, 10))
            continue

        # Headings
        if line.startswith("# "):
            title_text = line[2:].strip().replace("🏛️ ", "")
            story.append(Paragraph(title_text, title_style))
            story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0284c7'), spaceAfter=12))
            i += 1
            continue

        if line.startswith("## "):
            h1_text = line[3:].strip()
            story.append(Paragraph(h1_text, h1_style))
            i += 1
            continue

        if line.startswith("### "):
            h2_text = line[4:].strip()
            story.append(Paragraph(h2_text, h2_style))
            i += 1
            continue

        if line.startswith("#### "):
            h3_text = line[5:].strip()
            story.append(Paragraph(h3_text, h3_style))
            i += 1
            continue

        # Bullets (* or -)
        if line.strip().startswith("* ") or line.strip().startswith("- "):
            b_text = line.strip()[2:].strip()
            b_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', b_text)
            b_formatted = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', b_formatted)
            story.append(Paragraph(f"• {b_formatted}", bullet_style))
            i += 1
            continue

        # Numbered list
        if re.match(r'^\d+\.\s', line.strip()):
            n_text = re.sub(r'^\d+\.\s', '', line.strip())
            n_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', n_text)
            n_formatted = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', n_formatted)
            story.append(Paragraph(f"• {n_formatted}", bullet_style))
            i += 1
            continue

        # Normal Paragraph
        p_text = line.strip()
        p_formatted = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', p_text)
        p_formatted = re.sub(r'\*(.*?)\*', r'<i>\1</i>', p_formatted)
        p_formatted = re.sub(r'`(.*?)`', r'<font face="Courier">\1</font>', p_formatted)

        story.append(Paragraph(p_formatted, body_style))
        i += 1

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated: {pdf_filepath}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        md_file = os.path.abspath(sys.argv[1])
        pdf_file = os.path.splitext(md_file)[0] + ".pdf"
    else:
        md_file = "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/documentation/tech_architecture_document.md"
        pdf_file = "/Users/gauravchaudhary/Documents/Projects/Ai Projects/Hackathon/ADOS/documentation/tech_architecture_document.pdf"
    build_pdf(md_file, pdf_file)
