# runs inside the api container: /o is C:/Users/YiCheng/t615/620
set -u
W=http://web:8080; O=/o/shots; mkdir -p $O
shot() { name=$1; url=$2; widths=$3; shift 3; node tools/ops/screenshot.cjs --url "$W$url" --out $O --name "$name" --widths "$widths" "$@" >> $O/shots.jsonl 2>> $O/shots.err; echo "$name exit $?"; }
for s in TPEx/3147 TWSE/2892; do
  sym=${s#*/}
  shot "$sym-chart" "/stocks/$s" 1280,390 --click '#stock-tab-chart'
  shot "$sym-research" "/stocks/$s" 1280,390 --click '#stock-tab-research'
  shot "$sym-chart-1m" "/stocks/$s" 1280,390 --click '#stock-tab-chart' --click '.bars-range button:nth-child(1)'
  shot "$sym-chart-1y" "/stocks/$s" 1280,390 --click '#stock-tab-chart' --click '.bars-range button:nth-child(4)'
  shot "$sym-chart-week" "/stocks/$s" 1280,390 --click '#stock-tab-chart' --click '#bars-interval-tab-week'
done
shot "2330-chart" "/stocks/TWSE/2330" 1280,390 --click '#stock-tab-chart'
shot "market" "/market" 1280,390
