"""فاتورة مختصرة للطابعة الحرارية (80 أو 58 ملم) عبر طابعة ويندوز."""
import html
import logging

from PyQt5.QtCore import QMarginsF, QSizeF
from PyQt5.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt5.QtPrintSupport import QPrinter, QPrinterInfo

from ..money import fmt_money, fmt_qty, int_to_money, int_to_qty
from ..services import sales, settings

log = logging.getLogger(__name__)


def receipt_html(conn, sale_id) -> str:
    sale, items = sales.get_sale(conn, sale_id)
    s = settings.get_all(conn)
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(i['product_name'])}</td><td align=center>{fmt_qty(int_to_qty(i['qty']))}</td>"
        f"<td align=center>{fmt_money(int_to_money(i['unit_price']))}</td>"
        f"<td align=left>{fmt_money(int_to_money(i['line_total']))}</td></tr>"
        for i in items
    )
    kind = "نقدي" if sale["sale_type"] == "cash" else "آجل"
    extra = ""
    if sale["sale_type"] == "credit":
        bal = conn.execute("SELECT balance FROM customer_balances WHERE customer_id=?", (sale["customer_id"],)).fetchone()
        extra = (
            f"<p>العميل: {e(sale['customer_name'] or '')}<br>المدفوع: {fmt_money(int_to_money(sale['paid']))}"
            f"<br>المتبقي على الفاتورة: {fmt_money(int_to_money(sale['total'] - sale['paid']))}"
            f"<br>إجمالي رصيد العميل: {fmt_money(int_to_money(bal['balance']))}</p>"
        )
    return f"""
<html><body dir="rtl" style="font-family:'Noto Kufi Arabic',Tahoma,Arial;font-size:8pt;">
<div align="center"><b style="font-size:12pt">{e(s['shop_name'])}</b><br>{e(s['shop_address'])}<br>{e(s['shop_phone'])}</div>
<hr>
<p>فاتورة {kind} رقم: <b>{sale['id']}</b><br>التاريخ: {sale['created_at']}<br>الكاشير: {e(sale['user_full_name'] or sale['username'])}</p>
<table width="100%" cellspacing="0" cellpadding="1">
<tr><th align=right>الصنف</th><th>الكمية</th><th>السعر</th><th align=left>المبلغ</th></tr>
{rows}
</table><hr>
<p style="font-size:12pt"><b>الإجمالي: {fmt_money(int_to_money(sale['total']), True)}</b></p>
{extra}
<div align="center">{e(s['receipt_footer'])}</div>
</body></html>"""


def make_printer(conn, width_mm=80):
    name = settings.get(conn, "printer_name")
    info = QPrinterInfo.printerInfo(name) if name else QPrinterInfo.defaultPrinter()
    printer = QPrinter(info, QPrinter.HighResolution) if not info.isNull() else QPrinter(QPrinter.HighResolution)
    printer.setPageSize(QPageSize(QSizeF(width_mm, 297), QPageSize.Millimeter, "Receipt"))
    printer.setPageMargins(QMarginsF(2, 2, 2, 2), QPageLayout.Millimeter)
    return printer


def print_receipt(conn, sale_id) -> None:
    printer = make_printer(conn)
    doc = QTextDocument()
    doc.setHtml(receipt_html(conn, sale_id))
    doc.setPageSize(printer.pageRect(QPrinter.Point).size())
    doc.print_(printer)
