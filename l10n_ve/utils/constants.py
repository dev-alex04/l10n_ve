class DocumentTransactionType:
    __SALES_DOCTYPES__ = [
        'Quotation',
        'Sales Order',
        'Delivery Note',
        'Sales Invoice',
        'VE Sales Credit Note',
        'VE Sales Debit Note',
    ]

    __PURCHASE_DOCTYPES__ = [
        'Purchase Order',
        'Purchase Receipt',
        'Purchase Invoice',
        'Supplier Quotation',
    ]

    __SALES_INVOICE_DOCTYPES__ = [
        'Sales Invoice',
        'VE Sales Credit Note',
        'VE Sales Debit Note',
    ]

    __ALL_INVOICE_DOCTYPES__ = [
        'Purchase Invoice',
        'Sales Invoice',
        'VE Sales Credit Note',
        'VE Sales Debit Note',
    ]
