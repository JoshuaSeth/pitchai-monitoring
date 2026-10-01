# Native gnuplot 6.0 source. Run from this research directory after chart_data.
# Every data row comes from the retained anonymous tables and reviewed origins.
set encoding utf8
set datafile separator comma
set border 3 lc rgb '#87939d'
set tics nomirror
set grid xtics back lc rgb '#e0e5e9'
set style fill solid 0.85 border -1
set boxwidth 0.5
do for [format=1:2] {
    if (format==1) {set terminal svg size 1200,740 noenhanced font 'DejaVu Sans,14'; ext='svg'}
    if (format==2) {set terminal pngcairo size 1800,1110 noenhanced font 'DejaVu Sans,20'; ext='png'}
    set output 'figures/account-value.'.ext
    set multiplot layout 1,3 title 'Recovered account value relative to EUR200' font ',20' margins .07,.98,.25,.83 spacing .08,0
    set xrange [0:100]
    set yrange [8.7:.3]
    set xtics 20
    set ytics ('A01' 1,'A02' 2,'A03' 3,'A04' 4,'A05' 5,'A06' 6,'A07' 7,'A08' 8)
    set xlabel 'Reference EUR / EUR200'
    unset key
    do for [col=3:5] {
        if (col==5) {
            set label 1 'Dated standard API-equivalent value. Calendar periods contain incomplete observed days.' at screen .07,.14 left font ',12'
            set label 2 'Paid invoices and some account assignments are unverified. No monthly extrapolation.' at screen .07,.105 left font ',12'
            set label 3 'Source: tables/account_months.csv, strict_eligible=1. September is partial.' at screen .07,.07 left font ',12'
        }
        set title (col==3?'July':col==4?'August':'1-6 September (partial)')
        color=(col==5?'#a86727':'#246b83')
        plot 'figures/data/account-values.csv' using (column(col)/2):2:(column(col)/2):(.27) with boxxyerrorbars lc rgb color, \
             '' using (column(col)+2):2:(sprintf('%.1fx',column(col))) with labels left font ',12'
    }
    unset multiplot
    unset label

    set output 'figures/hourly-value.'.ext
    set title 'Dated value and constant-price comparison' font ',20' offset 0,1
    set lmargin at screen .29
    set rmargin at screen .98
    set bmargin at screen .29
    set tmargin at screen .83
    set xrange [0:38]
    set yrange [4.7:.3]
    set xtics 5
    set ytics ('Sol/max before 21 Aug' 1,'Sol/max 21-31 Aug' 2,'Sol/max 1-6 Sep' 3,'Astra/high 5-6 Sep' 4)
    set xlabel 'Standard API-equivalent USD per reported weekly point'
    set label 1 'Bars: dated prices. Diamonds: 6 September prices. Lines: +/-120 seconds and +/-1 point per interval.' at screen .07,.17 left font ',12'
    set label 2 'Conditional sensitivities are not confidence intervals and do not bound missing work or unknown tiers.' at screen .07,.13 left font ',12'
    set label 3 'Dominant model/effort >=95%. No pure xhigh cohort. Source: evidence/cohort-comparisons.json.' at screen .07,.09 left font ',12'
    plot 'figures/data/hourly-values.csv' using ($3/2):2:($3/2):(.23) with boxxyerrorbars lc rgb '#246b83', \
         '' using 3:2:5:6 with xerrorbars pt 0 lw 1.3 lc rgb '#212a33', \
         '' using 4:2 with points pt 13 ps 1.6 lc rgb '#dc9e22', \
         '' using (29.1):2:(sprintf('%d h / %d accounts',$7,$8)) with labels left font ',11'
    unset label

    set output 'figures/reset-epochs.'.ext
    set title 'Nearly complete quota windows by reset evidence' font ',20'
    set lmargin at screen .10
    set bmargin at screen .27
    set tmargin at screen .84
    set xdata time
    set timefmt '%Y-%m-%d'
    set format x '%d %b'
    set xrange ['2026-08-10':'2026-09-07']
    set yrange [0:30]
    set xtics 5*86400
    set ytics 5
    set grid xtics ytics
    set xlabel 'First positive observation in epoch (UTC)'
    set ylabel 'USD per reported point at 6 September prices'
    set key bottom left box opaque font ',11' maxcols 2
    array names[5]=['Direct guardian bank','Ordinary-compatible','Post-manual ambiguous','Probable bank','Unexplained replacement']
    array colors[5]=['#16816b','#212a33','#d28b26','#955b9e','#82929f']
    set arrow 1 from '2026-09-03',0 to '2026-09-03',30 nohead dt 2 lc rgb '#a34b62' back
    set label 1 'Astra available' at '2026-09-03',28.5 right textcolor rgb '#a34b62' font ',12'
    set label 2 'Each point: >=80 quota points, >=95% dominant model/effort and strict-source value, gap <=1,830 seconds.' at screen .10,.15 left font ',11'
    set label 3 'The three low September probable-bank points are Astra/high. Other eligible points are Sol/max.' at screen .10,.11 left font ',11'
    set label 4 'Sources: tables/epoch_analysis.csv + historical epoch annotations. Origin classes retain uncertainty.' at screen .10,.07 left font ',11'
    plot for [grade=1:5] 'figures/data/epoch-values.csv' using (timecolumn(3)):($5==grade?$4:1/0) \
         with points pt (grade+4) ps 1.5 lc rgb colors[grade] title names[grade]
    unset label
    unset arrow
    unset xdata
    set format x '%g'
    unset ylabel
    unset grid
    set grid xtics back lc rgb '#e0e5e9'
    set output
}
