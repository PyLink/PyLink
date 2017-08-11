#!/usr/bin/env python3
"""
Generates HTML versions of the mode list .csv definitions.
"""

import os
import os.path
import csv

os.chdir(os.path.dirname(__file__))

FILES = {
    'user-modes.csv': 'Supported User Modes for PyLink',
    'channel-modes.csv': 'Supported Channel Modes for PyLink'
}

def _write(outf, text):
    print(text, end='')
    outf.write(text)

for fname, title in FILES.items():
    outfname = os.path.splitext(fname)[0] + '.html'
    print('Generating HTML for %s to %s:' % (fname, outfname))
    with open(fname) as csvfile:
        csvdata = csv.reader(csvfile)

        with open(outfname, 'w') as outf:
            # CSS in HTML in Python, how lovely...
            _write(outf, """
<!DOCTYPE html>
<html lang="en">
<meta charset="UTF-8">
<meta name=viewport content="width=device-width, initial-scale=1">

<head>
<title>%s</title>
<style>

html {
    background-color: white;
}

.note {
    color: #555555;
}

/* (╮°-°)╮┳━┳ */
table, th, td {
    border: 1px solid black;
}

td, th {
    text-align: center;
    padding: 3px;
}

td:first-child, th[scope="row"] {
    text-align: left;
}

/* Table cells */
.tablecell-yes {
    background-color: #A7F2A5
}

.tablecell-no {
    background-color: #F08496
}

.tablecell-na {
    background-color: #F0F0F0
}

.tablecell-planned, .tablecell-yes2 {
    background-color: #92E8DF
}

.tablecell-partial {
    background-color: #EDE8A4
}

.tablecell-special {
    background-color: #DCB1FC
}

.tablecell-caveats {
    background-color: #F0C884
}

.tablecell-caveats2 {
    background-color: #ED9A80
}

.tablecell-no-padding {
    padding: initial;
}
</style>

</head>

<body>
<table>""" % title)
            notes = False
            for idx, row in enumerate(csvdata):
                if not any(row):  # Empty row
                    continue
                elif row[0] == '----':
                    notes = True
                    continue

                if notes:
                    _write(outf, "<p>%s</p>" % row[0])
                    continue

                _write(outf, "<tr>\n")
                for colidx, coltext in enumerate(row):
                    if idx == 0:
                        text = '<th scope="col">%s</th>\n' % coltext
                    elif colidx == 0:
                        text = '<th scope="row">%s</th>\n' % coltext
                    else:
                        # More formatting
                        if coltext:
                            coltext = '+' + coltext

                            try:
                                coltext, note = coltext.split(' ', 1)
                            except ValueError:
                                if coltext.endswith('*'):
                                    text = '<td class="tablecell-yes2">%s</td>' % coltext
                                else:
                                    text = '<td class="tablecell-yes">%s</td>' % coltext
                            else:
                                coltext = '%s<br><span class="note">%s</span>' % (coltext, note)
                                text = '<td class="tablecell-special">%s</td>' % coltext
                        else:
                            text = '<td class="tablecell-na note">n/a</td>'

                    _write(outf, text)

                _write(outf, "</tr>\n")
            _write(outf, """

</table>
</body>
</html>""")
