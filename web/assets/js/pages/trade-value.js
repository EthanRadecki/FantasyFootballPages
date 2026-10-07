/* Trade Value: every trade graded on four metrics and one composite score, QUAD (manager
   leaderboard, quality vs win %, trade network, trade explorer, most traded players, trades by
   week, all trades).

   Reads config.json and data/v1/trade-value.json (schema "trade-value"); trade-value-data.js turns
   the model into the shapes the page's script reads, as the Stage A build wrote them to data/*.js
   and inline. The script itself is the Stage A page's, run inside runPage() once the data is in
   (decision 7.14: same look first; its inline handlers stay on window until the design pass). What
   was written into the page now comes from the league:
     seasons         the model's seasons, the live one labelled "(live)"; colors from theme.season_colors
     managers        names, colors and logos from config.json (initials when a manager has no logo)
     excluded        the league's hidden managers and their seasons
     notes           the number of managers in the win % fit; the trades-by-week reading from the
                     league's editorial (notes.trade_week) */

import { config, load } from '../core/data.js';
import { managers } from '../core/managers.js';
import { drawNav, drawFooter, drawSubnav } from '../core/nav.js';
import { url, esc } from '../core/site.js';
import { chapterRail } from '../components/chapter-rail.js';
import { tradeData } from './trade-value-data.js';
import { methodNotes } from './transaction-notes.js';

var Chart = window.Chart;
var d3 = window.d3;
var cfg, mgr;
// the page's data (trade-value-data.js) and config
var PAGE_SEASONS, PAGE_LIVE_SEASON, SEASON_COLORS, MANAGER_COLORS, LEADERBOARD, LEADERBOARD_TOTALS, BEST_WORST, TRADES,
  QUAD_SCALE, TG_SCALE, RG_SCALE, FIT_SCALE, NEC_SCALE, NETWORK_DATA, WINPCT_DATA, TRADE_NODES, TRADE_WEEK_DATA, MOST_TRADED;

/* "2026 (live)" for the live season, else the year (shared.js on the Stage A site) */
function seasonLabel(s) {
  return PAGE_LIVE_SEASON !== null && String(s) === String(PAGE_LIVE_SEASON) ? s + ' (live)' : String(s);
}

/* a manager's logo by display name; an empty image (so the initials show) when there is none */
function logoSrc(name) {
  var m = mgr.find(name);
  return m && m.logo ? url(m.logo) : 'data:,';
}

/* the notes written from the league (see the header) */
function leagueNotes(M) {
  var hidden = mgr.all.filter(function (m) { return m.hidden; });
  var ex = document.getElementById('trade-excluded');
  if (hidden.length) {
    var their = Array.from(new Set([].concat.apply([], hidden.map(function (m) { return m.seasons || []; })))).sort();
    ex.innerHTML = ', and ' + esc(hidden.map(function (m) { return m.name; }).join(' / '))
      + (their.length ? ' (' + their.join(', ') + (their.length === 1 ? ' only' : '') + ')' : '')
      + (hidden.length === 1 ? ' is' : ' are') + ' excluded, same as the rest of the site';
  } else ex.remove();
  document.getElementById('winpct-count').textContent = String(WINPCT_DATA.length);
  var tw = document.getElementById('trade-week-note');
  if (M.notes && M.notes.trade_week) tw.textContent = ' ' + M.notes.trade_week; else tw.remove();
}

function runPage() {
  /* ── Shared red/gold/green gradient helper ── */
  // Trade Explorer's frame clamp (below) is desktop-only -- on a small
  // screen forcing everything into an already-tiny box just makes the
  // crowding worse, so mobile keeps the original free-floating behavior.
  var IS_MOBILE_VIEWPORT = window.matchMedia('(max-width: 768px)').matches;

  var GOOD = [90,138,90];
  var MID  = [212,175,55];
  var BAD  = [168,90,90];
  function lerp(a,b,t){ return Math.round(a+(b-a)*t); }
  function gradientColor(value, min, max, invert) {
    var p = max===min ? 0.5 : (value - min) / (max - min);
    if (invert) p = 1 - p;
    var c0 = p<=0.5 ? GOOD : MID;
    var c1 = p<=0.5 ? MID : BAD;
    var t = p<=0.5 ? p/0.5 : (p-0.5)/0.5;
    var r = lerp(c0[0],c1[0],t), g = lerp(c0[1],c1[1],t), b = lerp(c0[2],c1[2],t);
    return 'rgba('+r+','+g+','+b+',0.85)';
  }

  /* ── Generic column sort helper ── */
  function sortRows(rows, key, type, dir) {
    var sorted = rows.slice().sort(function(a,b){
      var av = a[key], bv = b[key];
      if (av === null || av === undefined) av = type === 'text' ? '' : -999;
      if (bv === null || bv === undefined) bv = type === 'text' ? '' : -999;
      if (type === 'text') { av = (av||'').toLowerCase(); bv = (bv||'').toLowerCase(); }
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  function wireSortableHeaders(tableId, renderFn, state) {
    document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(th){
      th.addEventListener('click', function(){
        var key = th.getAttribute('data-key');
        var type = th.getAttribute('data-type') || 'number';
        if (state.key === key) {
          state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.key = key;
          state.type = type;
          state.dir = 'desc';
        }
        document.querySelectorAll('#'+tableId+' th.sortable').forEach(function(h){
          h.classList.remove('sorted-asc','sorted-desc');
        });
        th.classList.add(state.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
        renderFn();
      });
    });
  }

  /* ── QUAD leaderboard chart ── */
  var currentQuadFilter = 'career';
  var quadChart = null;

  // Total QUAD per manager, career and each season (LEADERBOARD_TOTALS, from the data).
  var TOTAL_QUAD_ALL_VALUES = Object.keys(LEADERBOARD_TOTALS).reduce(function(acc, key){
    var filt = LEADERBOARD_TOTALS[key];
    return acc.concat(Object.keys(filt).map(function(m){ return filt[m]; }));
  }, []);
  var TOTAL_QUAD_SCALE = {
    min: Math.min.apply(null, TOTAL_QUAD_ALL_VALUES),
    max: Math.max.apply(null, TOTAL_QUAD_ALL_VALUES)
  };
  var currentQuadMetric = 'avg';

  function renderQuadPills() {
    var el = document.getElementById('quad-pills');
    var keys = ['career'].concat(PAGE_SEASONS.map(String));
    var html = '';
    keys.forEach(function(k) {
      var label = k === 'career' ? 'Career' : seasonLabel(k);
      var swatch = SEASON_COLORS[k] ? ' color-swatch-btn" style="--swatch-color:' + SEASON_COLORS[k] + ';' : '';
      html += '<button class="heatmap-season-pill'+(k==='career'?' active':'')+swatch+'" onclick="setQuadFilter(\''+k+'\', this)">'+label+'</button>';
    });
    el.innerHTML = html;
  }

  function renderQuadMetricToggle() {
    var el = document.getElementById('quad-metric-toggle');
    if (!el) return;
    var opts = [['avg','Average'],['total','Total']];
    var html = opts.map(function(o){
      return '<button class="heatmap-season-pill'+(currentQuadMetric===o[0]?' active':'')+'" onclick="setQuadMetric(\''+o[0]+'\', this)">'+o[1]+'</button>';
    }).join('');
    el.innerHTML = html;
  }

  function setQuadMetric(metric, btn) {
    currentQuadMetric = metric;
    if (btn) {
      btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
      btn.classList.add('active');
    }
    try { renderQuadChart(); } catch (e) { console.error('QUAD chart failed to render:', e); }
  }

  function setQuadFilter(filterKey, btn) {
    currentQuadFilter = filterKey;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    try { renderQuadChart(); } catch (e) { console.error('QUAD chart failed to render:', e); }
  }

  function renderQuadChart() {
    var pool = LEADERBOARD[currentQuadFilter] || {};
    var totalsPool = LEADERBOARD_TOTALS[currentQuadFilter] || {};
    var isTotal = currentQuadMetric === 'total';
    var scale = isTotal ? TOTAL_QUAD_SCALE : QUAD_SCALE;

    var rows = Object.keys(pool).map(function(m){
      return { m:m, avg:pool[m].quad, total:totalsPool[m], n:pool[m].n };
    });
    rows.sort(function(a,b){
      var av = isTotal ? a.total : a.avg, bv = isTotal ? b.total : b.avg;
      return bv - av;
    });
    var colors = rows.map(function(d){
      var v = isTotal ? d.total : d.avg;
      return gradientColor(v, scale.min, scale.max, true);
    });
    var bwLookup = (BEST_WORST[currentQuadFilter] || {});

    if (quadChart) { quadChart.destroy(); }
    var ctx = document.getElementById('chart-quad').getContext('2d');
    quadChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: rows.map(function(d){ return d.m; }),
        datasets: [{
          data: rows.map(function(d){ return isTotal ? d.total : d.avg; }),
          backgroundColor: colors,
          borderRadius: 4,
          barPercentage: 0.7,
          categoryPercentage: 0.8,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display:false },
          tooltip: {
            callbacks: {
              title: function(items) { return items[0].label; },
              label: function(ctx) {
                var d = rows[ctx.dataIndex];
                var lines = ['Avg QUAD: '+d.avg.toFixed(3), 'Total QUAD: '+(d.total>=0?'+':'')+d.total.toFixed(2), 'Trades: '+d.n];
                var bw = bwLookup[d.m];
                if (bw) {
                  lines.push('Best: '+bw.best.got.join('/')+' for '+bw.best.gave.join('/')+' ('+(bw.best.quad>=0?'+':'')+bw.best.quad.toFixed(2)+')');
                  lines.push('Worst: '+bw.worst.got.join('/')+' for '+bw.worst.gave.join('/')+' ('+(bw.worst.quad>=0?'+':'')+bw.worst.quad.toFixed(2)+')');
                }
                return lines;
              }
            }
          }
        },
        scales: {
          x: { min:scale.min, max:scale.max, title:{display:true,text: isTotal ? 'Total QUAD' : 'Average QUAD'} },
          y: {
            ticks:{
              autoSkip:false, font:{size:12},
              callback: function(value, index) {
                var d = rows[index];
                return d ? (d.m + ' (' + d.n + ')') : value;
              }
            }
          }
        }
      }
    });
  }

  var winpctChart = null;
  var logoImages = {};
  function preloadLogos(managers) {
    return Promise.all(managers.map(function(m) {
      return new Promise(function(resolve) {
        var logo = logoSrc(m);
        var img = new Image();
        img.onload = function(){ logoImages[m] = img; resolve(); };
        img.onerror = function(){ logoImages[m] = null; resolve(); };
        img.src = logo;
      });
    }));
  }

  var winPctQuadMin = -1, winPctQuadMax = 1;
  var logoPointsPlugin = {
    id: 'logoPoints',
    afterDatasetsDraw: function(chart) {
      var meta = chart.getDatasetMeta(1);
      if (!meta || !meta.data) return;
      var ctx = chart.ctx;
      meta.data.forEach(function(point, index) {
        var d = WINPCT_DATA[index];
        if (!d) return;
        var x = point.x, y = point.y;
        var r = (point.options && point.options.radius) || 14;
        var ringColor = gradientColor(d.avgQuad, winPctQuadMin, winPctQuadMax, true);
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI*2);
        ctx.fillStyle = '#f5f0e8';
        ctx.fill();
        ctx.lineWidth = 3;
        ctx.strokeStyle = ringColor;
        ctx.stroke();
        var img = logoImages[d.m];
        if (img) {
          ctx.save();
          ctx.beginPath();
          ctx.arc(x, y, Math.max(r-3,1), 0, Math.PI*2);
          ctx.clip();
          ctx.drawImage(img, x-(r-3), y-(r-3), (r-3)*2, (r-3)*2);
          ctx.restore();
        } else {
          ctx.fillStyle = ringColor;
          ctx.font = 'bold '+Math.max(9,r*0.55)+'px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          var initials = d.m.split(' ').filter(function(w){return w[0]===w[0].toUpperCase();}).map(function(w){return w[0];}).join('').slice(0,2);
          ctx.fillText(initials, x, y);
        }
        ctx.restore();
      });
    }
  };

  function renderWinPctLegend() {
    var el = document.getElementById('winpct-legend');
    var stops = [];
    for (var i = 0; i <= 8; i++) {
      var v = -1 + (i/8)*2;
      stops.push(gradientColor(v, -1, 1, true));
    }
    var gradCss = 'linear-gradient(to right, ' + stops.join(',') + ')';
    el.innerHTML =
      '<span>Ring: poor trades</span>' +
      '<div style="width:140px;height:10px;border-radius:5px;background:'+gradCss+';"></div>' +
      '<span>Ring: great trades</span>' +
      '<span style="margin-left:1.2rem;">Logo size = trades made</span>';
  }

  function linearRegression(points) {
    var n = points.length;
    var sumX=0, sumY=0, sumXY=0, sumXX=0;
    points.forEach(function(p){ sumX+=p.x; sumY+=p.y; sumXY+=p.x*p.y; sumXX+=p.x*p.x; });
    var slope = (n*sumXY - sumX*sumY) / (n*sumXX - sumX*sumX);
    var intercept = (sumY - slope*sumX) / n;
    return { slope: slope, intercept: intercept };
  }

  function renderWinPct() {
    renderWinPctLegend();

    var quads = WINPCT_DATA.map(function(d){return d.avgQuad;});
    winPctQuadMin = Math.min.apply(null, quads);
    winPctQuadMax = Math.max.apply(null, quads);
    var xPad = (winPctQuadMax - winPctQuadMin) * 0.12;

    var points = WINPCT_DATA.map(function(d){ return {x: d.avgQuad, y: d.winPct}; });
    var fit = linearRegression(points);
    var xLo = winPctQuadMin - xPad, xHi = winPctQuadMax + xPad;
    var trendLine = [
      {x: xLo, y: fit.slope*xLo + fit.intercept},
      {x: xHi, y: fit.slope*xHi + fit.intercept}
    ];

    if (winpctChart) { winpctChart.destroy(); }
    var ctx = document.getElementById('chart-winpct').getContext('2d');

    preloadLogos(WINPCT_DATA.map(function(d){return d.m;})).then(function(){
      try {
        winpctChart = new Chart(ctx, {
        type: 'bubble',
        data: {
          datasets: [
            {
              label: 'Best fit',
              data: trendLine,
              type: 'line',
              borderColor: 'rgba(90,90,90,0.55)',
              borderWidth: 2,
              borderDash: [6,4],
              pointRadius: 0,
              fill: false,
              order: 2,
            },
            {
              label: 'Managers',
              data: WINPCT_DATA.map(function(d){
                return { x: d.avgQuad, y: d.winPct, r: 12 + (d.trades/42)*18 };
              }),
              backgroundColor: 'transparent',
              borderColor: 'transparent',
              order: 1,
            }
          ]
        },
        plugins: [logoPointsPlugin],
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display:false },
            tooltip: {
              filter: function(item){ return item.datasetIndex === 1; },
              callbacks: {
                label: function(ctx){
                  var d = WINPCT_DATA[ctx.dataIndex];
                  return [
                    d.m,
                    'Win%: ' + d.winPct + '% (' + d.games + ' games)',
                    'Avg trade QUAD: ' + (d.avgQuad>=0?'+':'') + d.avgQuad.toFixed(2),
                    'Trades made: ' + d.trades
                  ];
                }
              }
            }
          },
          scales: {
            x: { title: {display:true, text:'Average QUAD per trade (career)'}, min:xLo, max:xHi },
            y: { title: {display:true, text:'Win percentage'}, min:0, max:100 }
          }
        }
      });
      } catch (e) {
        console.error('Win% chart failed to render after logo load:', e);
      }
    }).catch(function(e){
      console.error('Logo preload failed:', e);
    });
  }


  function renderNetwork() {
    var container = document.getElementById('network-container');
    var svg = d3.select('#network-svg');
    var tooltip = d3.select('#network-tooltip');
    var width = container.clientWidth, height = container.clientHeight;
    svg.attr('viewBox', [0,0,width,height]);
    svg.selectAll('*').remove();

    var radiusScale = d3.scaleSqrt().domain([0, d3.max(NETWORK_DATA.nodes, function(d){return d.trades;})]).range([10, 34]);
    var widthScale = d3.scaleSqrt().domain([1, d3.max(NETWORK_DATA.edges, function(d){return d.n;})]).range([1, 9]);

    var nodesById = {};
    NETWORK_DATA.nodes.forEach(function(n){ nodesById[n.id] = n; });

    var links = NETWORK_DATA.edges.map(function(e){ return {source: e.a, target: e.b, data: e}; });
    var nodes = NETWORK_DATA.nodes.map(function(n){ return Object.assign({}, n); });

    var simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(function(d){return d.id;}).distance(function(d){ return 90 + (10 - Math.min(d.data.n,10))*8; }))
      .force('charge', d3.forceManyBody().strength(-420))
      .force('center', d3.forceCenter(width/2, height/2))
      .force('collide', d3.forceCollide().radius(function(d){ return radiusScale(d.trades) + 14; }));

    var linkSel = svg.append('g').selectAll('line')
      .data(links).enter().append('line')
      .attr('stroke', '#9a8a70')
      .attr('stroke-opacity', 0.35)
      .attr('stroke-width', function(d){ return widthScale(d.data.n); })
      .style('cursor', 'pointer')
      .on('mouseover', function(event, d){
        d3.select(this).attr('stroke-opacity', 0.85).attr('stroke', '#5a7a8a');
        var posEntries = Object.entries(d.data.positions).sort(function(a,b){return b[1]-a[1];});
        var posStr = posEntries.map(function(p){return p[0]+': '+p[1];}).join(', ');
        var leader = d.data.netDiff > 0.05 ? d.data.a : (d.data.netDiff < -0.05 ? d.data.b : null);
        var edgeText = '<strong>'+d.data.a+' &harr; '+d.data.b+'</strong><br>'
          + d.data.n + ' trade'+(d.data.n===1?'':'s')+' together (' + d.data.seasons.join(', ') + ')<br>'
          + 'Positions exchanged: ' + posStr
          + (leader ? '<br><strong>'+leader+'</strong> has generally come out ahead' : '<br>Roughly even on average');
        tooltip.style('opacity', 1).html(edgeText)
          .style('left', (event.offsetX+14)+'px').style('top', (event.offsetY+14)+'px');
      })
      .on('mousemove', function(event){
        tooltip.style('left', (event.offsetX+14)+'px').style('top', (event.offsetY+14)+'px');
      })
      .on('mouseout', function(){
        d3.select(this).attr('stroke-opacity', 0.35).attr('stroke', '#9a8a70');
        tooltip.style('opacity', 0);
      });

    var nodeGroup = svg.append('g').selectAll('g')
      .data(nodes).enter().append('g')
      .style('cursor', 'grab')
      .call(d3.drag()
        .on('start', function(event,d){ if(!event.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
        .on('drag', function(event,d){ d.fx=event.x; d.fy=event.y; })
        .on('end', function(event,d){ if(!event.active) simulation.alphaTarget(0); d.fx=null; d.fy=null; }));

    nodeGroup.append('clipPath')
      .attr('id', function(d,i){ return 'node-clip-'+i; })
      .append('circle')
      .attr('r', function(d){ return Math.max(radiusScale(d.trades)-3, 1); });

    nodeGroup.append('circle')
      .attr('class', 'node-hit-area')
      .attr('r', function(d){ return radiusScale(d.trades); })
      .attr('fill', '#f5f0e8')
      .attr('stroke', function(d){
        var info = LEADERBOARD.career[d.id];
        var avgQuad = info ? info.quad : 0;
        return gradientColor(avgQuad, QUAD_SCALE.min, QUAD_SCALE.max, true);
      })
      .attr('stroke-width', 3)
      .on('mouseover', function(event, d){
        var partners = NETWORK_DATA.edges.filter(function(e){ return e.a===d.id || e.b===d.id; })
          .sort(function(a,b){ return b.n-a.n; }).slice(0,4);
        var partnerLines = partners.map(function(e){
          var other = e.a===d.id ? e.b : e.a;
          return other + ' (' + e.n + 'x)';
        }).join('<br>');
        var info = LEADERBOARD.career[d.id];
        var quadLine = info ? ('Avg trade QUAD: ' + (info.quad>=0?'+':'') + info.quad.toFixed(2) + '<br>') : '';
        var nodeText = '<strong>'+d.id+'</strong><br>'+d.trades+' total trades<br>'+quadLine+'Top partners:<br>'+partnerLines;
        tooltip.style('opacity', 1).html(nodeText)
          .style('left', (event.offsetX+14)+'px').style('top', (event.offsetY+14)+'px');
        linkSel.attr('stroke-opacity', function(l){ return (l.source.id===d.id || l.target.id===d.id) ? 0.85 : 0.08; });
      })
      .on('mousemove', function(event){
        tooltip.style('left', (event.offsetX+14)+'px').style('top', (event.offsetY+14)+'px');
      })
      .on('mouseout', function(){
        tooltip.style('opacity', 0);
        linkSel.attr('stroke-opacity', 0.35);
      })
      .on('click', function(event, d){ centerOnManager(d.id); });

    nodeGroup.each(function(d) {
      var g = d3.select(this);
      var r = radiusScale(d.trades);
      var i = nodes.indexOf(d);
      var logo = logoSrc(d.id);
      g.append('image')
        .attr('href', logo)
        .attr('x', -(r-3)).attr('y', -(r-3))
        .attr('width', (r-3)*2).attr('height', (r-3)*2)
        .attr('clip-path', 'url(#node-clip-'+i+')')
        .style('pointer-events', 'none')
        .on('error', function(){
          d3.select(this).remove();
          g.append('text')
            .text(d.id.split(' ').filter(function(w){return w[0]===w[0].toUpperCase();}).map(function(w){return w[0];}).join('').slice(0,2))
            .attr('text-anchor', 'middle').attr('dy', '0.35em')
            .attr('font-size', '11px').attr('font-weight', '700')
            .attr('fill', function(){
              var info = LEADERBOARD.career[d.id];
              var avgQuad = info ? info.quad : 0;
              return gradientColor(avgQuad, QUAD_SCALE.min, QUAD_SCALE.max, true);
            })
            .style('pointer-events', 'none');
        });
    });

    nodeGroup.append('title').text(function(d){ return d.id; });

    simulation.on('tick', function(){
      linkSel
        .attr('x1', function(d){return d.source.x;}).attr('y1', function(d){return d.source.y;})
        .attr('x2', function(d){return d.target.x;}).attr('y2', function(d){return d.target.y;});
      nodeGroup.attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
    });

    // Click a manager to pin them at the center and arrange everyone else
    // evenly around them in a circle, ordered by how many times they've
    // traded with the center (strongest partnerships land near the top).
    // Nodes stay draggable afterward -- dragging any node already releases
    // its pin via the existing drag handlers above, so the free-form
    // physics is still there whenever you want it, just not the default
    // view anymore for whatever you haven't touched.
    function centerOnManager(managerId) {
      var center = nodes.find(function(n){ return n.id === managerId; });
      if (!center) return;

      var cx = width / 2, cy = height / 2;
      var radius = Math.min(width, height) * 0.36;

      var tradeCountWith = {};
      NETWORK_DATA.edges.forEach(function(e){
        if (e.a === managerId) tradeCountWith[e.b] = e.n;
        else if (e.b === managerId) tradeCountWith[e.a] = e.n;
      });
      var others = nodes.filter(function(n){ return n.id !== managerId; })
        .sort(function(a,b){ return (tradeCountWith[b.id]||0) - (tradeCountWith[a.id]||0); });

      var targets = {};
      targets[managerId] = { x: cx, y: cy };
      var angleStep = (2 * Math.PI) / Math.max(others.length, 1);
      others.forEach(function(n, i){
        var angle = -Math.PI/2 + i * angleStep;
        targets[n.id] = { x: cx + radius*Math.cos(angle), y: cy + radius*Math.sin(angle) };
      });

      simulation.stop();
      var duration = 700;
      var starts = nodes.map(function(n){ return { n: n, x: n.x, y: n.y }; });
      var timer = d3.timer(function(elapsed){
        var t = Math.min(elapsed / duration, 1);
        var e = d3.easeCubicInOut(t);
        starts.forEach(function(s){
          var target = targets[s.n.id];
          s.n.x = s.x + (target.x - s.x) * e;
          s.n.y = s.y + (target.y - s.y) * e;
        });
        linkSel.attr('x1', function(d){return d.source.x;}).attr('y1', function(d){return d.source.y;})
               .attr('x2', function(d){return d.target.x;}).attr('y2', function(d){return d.target.y;});
        nodeGroup.attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
        if (t >= 1) {
          timer.stop();
          nodes.forEach(function(n){ var tgt = targets[n.id]; n.fx = tgt.x; n.fy = tgt.y; });
        }
      });
    }

    // Escape hatch back to fully free-form physics, in case pinning
    // everything into the radial layout isn't what's wanted anymore.
    window.resetNetworkLayout = function(){
      nodes.forEach(function(n){ n.fx = null; n.fy = null; });
      simulation.alpha(1).restart();
    };
  }

  /* ── Most Traded Players chart ── */
  var mostTradedChart = null;
  var mostTradedPosFilter = 'all';

  var POS_BAR_COLOR = {
    'QB':   'rgba(168,90,90,0.85)',
    'RB':   'rgba(90,138,90,0.85)',
    'WR':   'rgba(74,127,168,0.85)',
    'TE':   'rgba(212,175,55,0.85)',
    'K':    'rgba(156,148,156,0.85)',
    'D/ST': 'rgba(100,90,80,0.85)',
  };
  var POS_BADGE_CLASS = {
    'QB': 'pos-qb', 'RB': 'pos-rb', 'WR': 'pos-wr',
    'TE': 'pos-te', 'K': 'pos-k', 'D/ST': 'pos-dst',
  };
  // Position colors (solid hex, for filter-pill swatches) -- same palette
  // as the canonical .pos-badge system and POS_BAR_COLOR above.
  var POSITION_COLORS = {
    QB: '#983a3a', RB: '#4a7a4a', WR: '#3a6f98',
    TE: '#a07010', K: '#6a6460', 'D/ST': '#504840'
  };

  function renderMostTradedPosPills() {
    var el = document.getElementById('most-traded-pos-pills');
    if (!el) return;
    var positions = Array.from(new Set(MOST_TRADED.map(function(d){ return d.pos; })));
    // Fixed, sensible order rather than whatever order first-appears in the data
    var order = ['QB','RB','WR','TE','K','D/ST'];
    positions.sort(function(a,b){ return order.indexOf(a) - order.indexOf(b); });

    var html = '<button class="heatmap-season-pill active" onclick="setMostTradedPosFilter(\'all\', this)">All Positions</button>';
    positions.forEach(function(p) {
      var swatch = POSITION_COLORS[p] ? ' color-swatch-btn" style="--swatch-color:' + POSITION_COLORS[p] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setMostTradedPosFilter(\'' + p + '\', this)">' + p + '</button>';
    });
    el.innerHTML = html;
  }

  function setMostTradedPosFilter(pos, btn) {
    mostTradedPosFilter = pos;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderMostTraded();
  }

  function renderMostTraded() {
    var filtered = mostTradedPosFilter === 'all'
      ? MOST_TRADED
      : MOST_TRADED.filter(function(d){ return d.pos === mostTradedPosFilter; });
    var top = filtered.slice(0, 20);
    var colors = top.map(function(d){ return POS_BAR_COLOR[d.pos] || 'rgba(156,148,156,0.85)'; });

    if (mostTradedChart) { mostTradedChart.destroy(); }
    var ctx = document.getElementById('chart-most-traded').getContext('2d');
    mostTradedChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: top.map(function(d){return d.player;}),
        datasets: [{
          label: 'Times Traded',
          data: top.map(function(d){return d.count;}),
          backgroundColor: colors,
          borderRadius: 4,
          barPercentage: 0.75,
          categoryPercentage: 0.8,
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display:false },
          tooltip: {
            callbacks: {
              title: function(ctxArr){
                var d = top[ctxArr[0].dataIndex];
                return d.player + ' (' + d.pos + ')';
              },
              label: function(ctx){
                var d = top[ctx.dataIndex];
                var lines = ['Traded ' + d.count + ' times', 'Seasons: ' + d.seasons.join(', ')];
                lines.push('Traded to: ' + d.managers.join(', '));
                return lines;
              }
            }
          }
        },
        scales: {
          x: { title: {display:true, text:'Times traded'} },
          y: { ticks: { autoSkip:false, font:{size:11} } }
        }
      }
    });
  }

  // Trades by week of the season: trade count (bars) and average QUAD
  // (line) grouped by the week each trade happened. TRADE_WEEK_DATA has
  // one row per manager's side of a trade (same shape as TRADES elsewhere
  // on this page), so counting distinct group ids avoids double-counting
  // multi-team trades. Season-filterable; no position or weeks-rostered
  // equivalent exists for trades, so those filters are intentionally left
  // out rather than forcing a substitute that doesn't map to anything real.
  var tradeWeekChart = null;
  var tradeWeekSeasonFilter = 'career';
  var tradeWeekLastClicked = null;
  // True population min/max of QUAD across every trade in TRADE_WEEK_DATA,
  // computed once -- not guessed -- so the detail panel's color gradient
  // reflects the real range of outcomes, the same way the site's other
  // gradient scales are all derived from actual data rather than assumed.
  var TRADE_WEEK_QUAD_MIN = Math.min.apply(null, TRADE_WEEK_DATA.map(function(r){ return r.quad; }));
  var TRADE_WEEK_QUAD_MAX = Math.max.apply(null, TRADE_WEEK_DATA.map(function(r){ return r.quad; }));

  function renderTradeWeekFilters() {
    var el = document.getElementById('trade-week-season-pills');
    if (!el) return;
    var seasons = Array.from(new Set(TRADE_WEEK_DATA.map(function(r){ return r.s; }))).sort();
    var html = '<button class="heatmap-season-pill active" onclick="setTradeWeekSeason(\'career\', this)">Career</button>';
    seasons.forEach(function(s){
      var swatch = SEASON_COLORS[s] ? ' color-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setTradeWeekSeason('+s+', this)">'+s+'</button>';
    });
    el.innerHTML = html;
  }

  function setTradeWeekSeason(season, btn) {
    tradeWeekSeasonFilter = season;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTradeWeekChart();
    if (tradeWeekLastClicked !== null) renderTradeWeekDetail(tradeWeekLastClicked);
  }

  function renderTradeWeekChart() {
    var pool = TRADE_WEEK_DATA.filter(function(r){
      return tradeWeekSeasonFilter === 'career' || r.s === tradeWeekSeasonFilter;
    });

    var maxWeek = 17;
    var byWeek = {};
    for (var w = 1; w <= maxWeek; w++) byWeek[w] = { groups: {}, quadSum: 0, n: 0 };
    pool.forEach(function(r){
      var b = byWeek[r.wk];
      if (!b) return;
      b.groups[r.g] = true;
      b.quadSum += r.quad;
      b.n++;
    });

    var labels = [], tradeCounts = [], avgQuads = [];
    for (var wk = 1; wk <= maxWeek; wk++) {
      var b = byWeek[wk];
      labels.push('Wk ' + wk);
      tradeCounts.push(Object.keys(b.groups).length);
      avgQuads.push(b.n ? +(b.quadSum / b.n).toFixed(3) : null);
    }

    if (tradeWeekChart) { tradeWeekChart.destroy(); }
    var ctx = document.getElementById('chart-trade-week').getContext('2d');
    tradeWeekChart = new Chart(ctx, {
      data: {
        labels: labels,
        datasets: [
          {
            type: 'bar',
            label: 'Trades',
            data: tradeCounts,
            backgroundColor: 'rgba(74,127,168,0.85)',
            yAxisID: 'yCount',
            order: 2,
          },
          {
            type: 'line',
            label: 'Avg QUAD',
            data: avgQuads,
            borderColor: '#c0623a',
            backgroundColor: 'rgba(192,98,58,0.1)',
            borderWidth: 2.5,
            pointRadius: 3,
            pointBackgroundColor: '#c0623a',
            tension: 0.3,
            spanGaps: true,
            yAxisID: 'yValue',
            order: 1,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        onHover: function(event, elements) {
          event.native.target.style.cursor = elements.length ? 'pointer' : 'default';
        },
        onClick: function(event, elements) {
          if (!elements.length) return;
          var weekIndex = elements[0].index;
          tradeWeekLastClicked = weekIndex + 1;
          renderTradeWeekDetail(tradeWeekLastClicked);
        },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { boxWidth: 12, padding: 14 } }
        },
        scales: {
          x: { grid: { display: false } },
          yCount: {
            position: 'left',
            title: { display: true, text: 'Trades' },
            ticks: { precision: 0 }
          },
          yValue: {
            position: 'right',
            title: { display: true, text: 'Average QUAD' },
            grid: { drawOnChartArea: false }
          }
        }
      }
    });
  }

  // Detail panel for a clicked week bar: every trade from that week,
  // respecting the active season filter, deduplicated to one row per
  // trade (both sides shown together) rather than one row per manager.
  function renderTradeWeekDetail(week) {
    var panel = document.getElementById('trade-week-detail');
    if (!panel) return;
    var pool = TRADE_WEEK_DATA.filter(function(r){
      if (r.wk !== week) return false;
      return tradeWeekSeasonFilter === 'career' || r.s === tradeWeekSeasonFilter;
    });

    var byGroup = {};
    pool.forEach(function(r){
      if (!byGroup[r.g]) byGroup[r.g] = [];
      byGroup[r.g].push(r);
    });
    var groups = Object.keys(byGroup).map(function(g){ return byGroup[g]; });
    groups.sort(function(a,b){
      var maxA = Math.max.apply(null, a.map(function(r){return Math.abs(r.quad);}));
      var maxB = Math.max.apply(null, b.map(function(r){return Math.abs(r.quad);}));
      return maxB - maxA;
    });

    var seasonLabel = tradeWeekSeasonFilter === 'career'
      ? '<span style="color:var(--muted);font-weight:600;">Career</span>'
      : '<span class="season-pill" style="background:'+(SEASON_COLORS[tradeWeekSeasonFilter]||'var(--muted)')+';font-size:0.8rem;">'+tradeWeekSeasonFilter+'</span>';

    // Each trade group's rows stay exactly as they were. Between groups
    // (not between sides of the same trade) a dedicated, empty spacer row
    // carries the dashed line on its own border -- this sidesteps
    // border-collapse conflict resolution entirely (a cell-level border
    // competing with the existing row separator can lose or get dropped
    // depending on the browser, which is why the sibling-selector version
    // of this didn't reliably show up), so it renders the same everywhere.
    var groupsHtml = groups.map(function(sides, gi){
      var multiTag = sides[0].multi ? '<span class="multi-badge">MULTI</span>' : '';
      var seasonTag = tradeWeekSeasonFilter === 'career'
        ? '<span class="season-pill" style="background:'+(SEASON_COLORS[sides[0].s]||'var(--muted)')+';">'+sides[0].s+'</span> '
        : '';
      var rows = sides.map(function(r){
        var mColor = MANAGER_COLORS[r.m] || 'var(--palm)';
        var quadBg = gradientColor(r.quad, TRADE_WEEK_QUAD_MIN, TRADE_WEEK_QUAD_MAX, true);
        var row = '<tr>'
          + '<td>'+seasonTag+multiTag+'</td>'
          + '<td style="font-weight:600;color:'+mColor+';">'+r.m+'</td>'
          + '<td class="got-txt">'+(r.got.length ? r.got.join(', ') : '&ndash;')+'</td>'
          + '<td class="gave-txt">'+(r.gave.length ? r.gave.join(', ') : '&ndash;')+'</td>'
          + '<td><span style="background:'+quadBg+';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">'+(r.quad>=0?'+':'')+r.quad.toFixed(2)+'</span></td>'
          + '</tr>';
        seasonTag = ''; multiTag = '';
        return row;
      }).join('');
      var divider = gi > 0 ? '<tr class="tw-divider"><td colspan="5"></td></tr>' : '';
      return divider + rows;
    }).join('');

    var countNote = groups.length + ' trade' + (groups.length === 1 ? '' : 's') + ' this week' + (tradeWeekSeasonFilter === 'career' ? ' across all seasons.' : ' in ' + tradeWeekSeasonFilter + '.');

    panel.innerHTML =
      '<div class="detail-panel-label">Week Details</div>'
      + '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">'
        + '<span style="font-family:var(--font-display);font-weight:800;font-size:1.05rem;color:var(--palm);">Week '+week+'</span>'
        + seasonLabel
      + '</div>'
      + (groups.length === 0
          ? '<p style="font-size:0.85rem;color:var(--muted);">No trades happened this week for this filter.</p>'
          : '<div class="table-wrap" style="overflow-x:auto;padding:0;">'
            + '<table class="tv-table tw-table"><thead><tr><th>Season</th><th>Manager</th><th>Got</th><th>Gave</th><th>QUAD</th></tr></thead>'
            + '<tbody>' + groupsHtml + '</tbody></table></div>'
            + '<p class="metric-note" style="margin-top:0.5rem;">'+countNote+'</p>');
    panel.style.display = 'block';
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    panel.classList.remove('flash');
    void panel.offsetWidth;
    panel.classList.add('flash');
  }


  /* ── Trade Explorer (bipartite manager<->trade graph) ── */
  var explorerState = { season: 'all', type: 'all', managerA: 'any', managerB: 'any' };
  var explorerSimulation = null;

  function explorerPill(container, label, value, isActive, onClick, swatchColor) {
    var btn = document.createElement('div');
    btn.className = 'heatmap-season-pill' + (isActive ? ' active' : '') + (swatchColor ? ' color-swatch-btn' : '');
    if (swatchColor) btn.style.setProperty('--swatch-color', swatchColor);
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    container.appendChild(btn);
  }

  function renderExplorerFilters() {
    var seasons = [...new Set(TRADE_NODES.map(function(n){return n.season;}))].sort();
    var managers = [...new Set(TRADE_NODES.flatMap(function(n){ return n.managers.map(function(m){return m.m;}); }))].sort();

    var seasonEl = document.getElementById('explorer-season-pills');
    seasonEl.innerHTML = '';
    explorerPill(seasonEl, 'All Seasons', 'all', explorerState.season==='all', function(){ explorerState.season='all'; renderExplorerFilters(); renderExplorer(); });
    seasons.forEach(function(s){
      explorerPill(seasonEl, s, s, explorerState.season===s, function(){ explorerState.season=s; renderExplorerFilters(); renderExplorer(); }, SEASON_COLORS[s]);
    });

    var typeEl = document.getElementById('explorer-type-pills');
    typeEl.innerHTML = '';
    [['all','All'],['2team','2-Team Only'],['multi','Multi-Team Only']].forEach(function(t){
      explorerPill(typeEl, t[1], t[0], explorerState.type===t[0], function(){ explorerState.type=t[0]; renderExplorerFilters(); renderExplorer(); });
    });

    var aEl = document.getElementById('explorer-manager-a-pills');
    aEl.innerHTML = '';
    explorerPill(aEl, 'Any', 'any', explorerState.managerA==='any', function(){ explorerState.managerA='any'; explorerState.managerB='any'; renderExplorerFilters(); renderExplorer(); });
    managers.forEach(function(m){
      explorerPill(aEl, m, m, explorerState.managerA===m, function(){ explorerState.managerA = (explorerState.managerA===m ? 'any' : m); renderExplorerFilters(); renderExplorer(); }, MANAGER_COLORS[m]);
    });

    var bEl = document.getElementById('explorer-manager-b-pills');
    bEl.innerHTML = '';
    if (explorerState.managerA === 'any') {
      bEl.innerHTML = '<span style="font-size:0.78rem;color:var(--muted);">Pick Manager A first</span>';
    } else {
      explorerPill(bEl, 'Any', 'any', explorerState.managerB==='any', function(){ explorerState.managerB='any'; renderExplorerFilters(); renderExplorer(); });
      managers.filter(function(m){return m!==explorerState.managerA;}).forEach(function(m){
        explorerPill(bEl, m, m, explorerState.managerB===m, function(){ explorerState.managerB = (explorerState.managerB===m ? 'any' : m); renderExplorerFilters(); renderExplorer(); }, MANAGER_COLORS[m]);
      });
    }
  }

  function getFilteredTradeNodes() {
    return TRADE_NODES.filter(function(n){
      if (explorerState.season !== 'all' && n.season !== explorerState.season) return false;
      if (explorerState.type === '2team' && n.multi) return false;
      if (explorerState.type === 'multi' && !n.multi) return false;
      var names = n.managers.map(function(m){return m.m;});
      if (explorerState.managerA !== 'any' && names.indexOf(explorerState.managerA) === -1) return false;
      if (explorerState.managerB !== 'any' && names.indexOf(explorerState.managerB) === -1) return false;
      return true;
    });
  }

  function renderTradeDetail(node) {
    var panel = document.getElementById('explorer-detail');
    var rows = node.managers.map(function(m){
      var quadBg = gradientColor(m.quad, QUAD_SCALE.min, QUAD_SCALE.max, true);
      var necDisplay = m.nec === null ? '&ndash;' : m.nec.toFixed(1);
      return '<tr>'
        + '<td style="font-weight:600;color:var(--palm);">'+m.m+'</td>'
        + '<td class="got-txt">'+m.got.join(', ')+'</td>'
        + '<td class="gave-txt">'+m.gave.join(', ')+'</td>'
        + '<td>'+m.tg.toFixed(1)+'</td>'
        + '<td>'+m.rg.toFixed(1)+'</td>'
        + '<td>'+m.fit.toFixed(2)+'</td>'
        + '<td>'+necDisplay+'</td>'
        + '<td><span style="background:'+quadBg+';color:#fff;padding:0.12rem 0.45rem;border-radius:4px;font-weight:700;">'+m.quad.toFixed(2)+'</span></td>'
        + '</tr>';
    }).join('');

    var seasonColor = SEASON_COLORS[node.season] || 'var(--muted)';
    panel.innerHTML =
      '<div id="explorer-detail-label">Trade Details</div>'
      + '<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">'
        + '<span class="season-pill" style="background:'+seasonColor+';font-size:0.8rem;">'+node.season+'</span>'
        + (node.multi ? '<span class="multi-badge">'+node.managers.length+'-TEAM</span>' : '')
      + '</div>'
      + '<div style="font-size:0.78rem;color:var(--muted);margin-bottom:0.75rem;">Positions involved: ' + (node.positions.join(', ') || '&ndash;') + '</div>'
      + '<div class="table-wrap" style="overflow-x:auto;">'
      + '<table class="tv-table"><thead><tr><th>Manager</th><th>Got</th><th>Gave</th><th>Trade Grade</th><th>Realized Gains</th><th>Fit</th><th>Necessity/wk</th><th>QUAD</th></tr></thead>'
      + '<tbody>'+rows+'</tbody></table></div>';
    panel.style.display = 'block';

    // Make it obvious something just appeared: scroll it into view (the
    // graph can be tall enough that the panel opens below the fold,
    // especially on mobile) and give it a quick attention flash. The
    // reflow trick lets the flash re-trigger even if you click several
    // diamonds in a row without the animation getting stuck mid-way.
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    panel.classList.remove('flash');
    void panel.offsetWidth;
    panel.classList.add('flash');
  }

  function renderExplorer() {
    var filtered = getFilteredTradeNodes();
    var container = document.getElementById('explorer-container');
    var svg = d3.select('#explorer-svg');
    var emptyMsg = document.getElementById('explorer-empty');
    var tooltip = d3.select('#explorer-tooltip');
    document.getElementById('explorer-detail').style.display = 'none';

    svg.selectAll('*').remove();
    if (explorerSimulation) { explorerSimulation.stop(); }

    if (filtered.length === 0) {
      emptyMsg.style.display = 'flex';
      return;
    }
    emptyMsg.style.display = 'none';

    var width = container.clientWidth, height = container.clientHeight;
    svg.attr('viewBox', [0,0,width,height]);

    var managerNames = [...new Set(filtered.flatMap(function(n){ return n.managers.map(function(m){return m.m;}); }))];

    var graphNodes = [];
    managerNames.forEach(function(m){ graphNodes.push({ type:'manager', id:'mgr:'+m, name:m }); });
    filtered.forEach(function(n){ graphNodes.push({ type:'trade', id:'trade:'+n.gid, data:n }); });

    var links = [];
    filtered.forEach(function(n){
      n.managers.forEach(function(m){
        links.push({ source:'mgr:'+m.m, target:'trade:'+n.gid });
      });
    });

    var sim = d3.forceSimulation(graphNodes)
      .force('link', d3.forceLink(links).id(function(d){return d.id;}).distance(70))
      .force('charge', d3.forceManyBody().strength(-260))
      .force('center', d3.forceCenter(width/2, height/2))
      .force('collide', d3.forceCollide().radius(function(d){ return d.type==='manager' ? 26 : (d.data.managers.length>=3 ? 20 : 14); }));
    explorerSimulation = sim;

    var linkSel = svg.append('g').selectAll('line')
      .data(links).enter().append('line')
      .attr('stroke', '#9a8a70').attr('stroke-opacity', 0.4).attr('stroke-width', 1.5);

    var nodeGroup = svg.append('g').selectAll('g')
      .data(graphNodes).enter().append('g')
      .style('cursor', function(d){ return d.type==='trade' ? 'pointer' : 'grab'; })
      .call(d3.drag()
        .on('start', function(event,d){ if(!event.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
        .on('drag', function(event,d){ d.fx=event.x; d.fy=event.y; })
        .on('end', function(event,d){ if(!event.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }));

    nodeGroup.each(function(d, i){
      var g = d3.select(this);
      if (d.type === 'manager') {
        var r = 22;
        g.append('clipPath').attr('id','exp-clip-'+i).append('circle').attr('r', r-2);
        g.append('circle').attr('r', r).attr('fill', '#f5f0e8').attr('stroke', '#9a8a70').attr('stroke-width', 2);
        var logo = logoSrc(d.name);
        g.append('image')
          .attr('href', logo)
          .attr('x', -(r-2)).attr('y', -(r-2)).attr('width', (r-2)*2).attr('height', (r-2)*2)
          .attr('clip-path', 'url(#exp-clip-'+i+')')
          .style('pointer-events','none')
          .on('error', function(){
            d3.select(this).remove();
            g.append('text').text(d.name.split(' ').filter(function(w){return w[0]===w[0].toUpperCase();}).map(function(w){return w[0];}).join('').slice(0,2))
              .attr('text-anchor','middle').attr('dy','0.35em').attr('font-size','11px').attr('font-weight','700')
              .attr('fill','#6b5f50').style('pointer-events','none');
          });
        g.on('click', function(){
          // Selecting a manager both narrows the filter (fewer nodes,
          // less crowding) and centers the result on them, same idea as
          // the Trade Network graph's click-to-center.
          explorerState.managerA = d.name;
          explorerState.managerB = 'any';
          renderExplorerFilters();
          renderExplorer();
        });
        g.on('mouseenter', function(){
          linkSel.attr('stroke-opacity', function(l){ return (l.source.id===d.id || l.target.id===d.id) ? 0.85 : 0.08; });
        });
        g.on('mouseleave', function(){ linkSel.attr('stroke-opacity', 0.4); });
        g.append('title').text(d.name);
      } else {
        var n = d.data;
        var maxQuad = Math.max.apply(null, n.managers.map(function(m){return m.quad;}));
        var color = gradientColor(maxQuad, QUAD_SCALE.min, QUAD_SCALE.max, true);
        var size = n.managers.length >= 3 ? 15 : 10;
        g.append('path')
          .attr('d', d3.symbol().type(d3.symbolDiamond).size(size*size*2.2))
          .attr('fill', color).attr('fill-opacity', 0.85).attr('stroke', '#f5f0e8').attr('stroke-width', 1.5)
          .on('mouseover', function(event){
            var names = n.managers.map(function(m){return m.m;}).join(', ');
            tooltip.style('opacity',1).html('<strong>'+n.season+':</strong> '+names+(n.multi?' (multi-team)':''))
              .style('left',(event.offsetX+12)+'px').style('top',(event.offsetY+12)+'px');
            linkSel.attr('stroke-opacity', function(l){ return (l.source.id===d.id || l.target.id===d.id) ? 0.85 : 0.08; });
          })
          .on('mousemove', function(event){
            tooltip.style('left',(event.offsetX+12)+'px').style('top',(event.offsetY+12)+'px');
          })
          .on('mouseout', function(){ tooltip.style('opacity',0); linkSel.attr('stroke-opacity', 0.4); })
          .on('click', function(){ renderTradeDetail(n); });
      }
    });

    sim.on('tick', function(){
      // Nothing above constrains node positions to the visible frame --
      // forceCenter only pulls the average position toward center, it
      // doesn't stop any individual node from drifting past the edges.
      // Clamp explicitly instead, using each node's own radius so circles
      // and diamonds stay fully on-screen rather than getting clipped.
      // Desktop only -- see IS_MOBILE_VIEWPORT above.
      if (!IS_MOBILE_VIEWPORT) {
        var pad = 16;
        graphNodes.forEach(function(d){
          var r = d.type === 'manager' ? 22 : (d.data.managers.length >= 3 ? 15 : 10);
          d.x = Math.max(r + pad, Math.min(width - r - pad, d.x));
          d.y = Math.max(r + pad, Math.min(height - r - pad, d.y));
        });
      }
      linkSel
        .attr('x1', function(d){return d.source.x;}).attr('y1', function(d){return d.source.y;})
        .attr('x2', function(d){return d.target.x;}).attr('y2', function(d){return d.target.y;});
      nodeGroup.attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
    });

    // Whenever a specific manager is selected (via clicking their node
    // above, or the Manager A pill), pin them at the center and ring
    // everyone still on screen evenly around them: their trade partners
    // first (most shared trades nearest the top), then the trade diamonds
    // themselves in chronological order. Same idea as the Trade Network
    // graph, adapted for this graph's two node types.
    function centerExplorerOn(managerName) {
      var center = graphNodes.find(function(n){ return n.type === 'manager' && n.name === managerName; });
      if (!center) return;

      var cx = width / 2, cy = height / 2;
      // Trade diamonds go on the INNER ring and managers on the OUTER ring,
      // not the other way around -- every diamond connects directly to the
      // center (the filter guarantees the center manager is in every trade
      // shown), so putting diamonds outer forced those lines to cross
      // straight through the manager ring to get there. Diamonds inner
      // keeps those center-to-diamond lines short and uncluttered; only
      // the diamond-to-partner lines have to reach further out.
      var tradeRadius = Math.min(width, height) * 0.24;
      var mgrRadius = Math.min(width, height) * 0.42;

      var otherManagers = graphNodes.filter(function(n){ return n.type === 'manager' && n.name !== managerName; });
      var tradeNodesArr = graphNodes.filter(function(n){ return n.type === 'trade'; });

      tradeNodesArr.sort(function(a,b){ return a.data.season - b.data.season; });

      var targets = {};
      targets[center.id] = { x: cx, y: cy };

      var tradeAngleStep = (2 * Math.PI) / Math.max(tradeNodesArr.length, 1);
      var tradeAngle = {};
      tradeNodesArr.forEach(function(n, i){
        var angle = -Math.PI/2 + i * tradeAngleStep;
        tradeAngle[n.id] = angle;
        targets[n.id] = { x: cx + tradeRadius*Math.cos(angle), y: cy + tradeRadius*Math.sin(angle) };
      });

      // Order managers by the circular mean angle of the diamonds they
      // share with the center, so a partner lands roughly "behind" their
      // trades instead of at a spot decided purely by trade count -- this
      // makes the diamond-to-partner lines read as a comb/fan instead of
      // crossing diagonally across the whole circle.
      otherManagers.forEach(function(m){
        var angles = filtered
          .filter(function(n){ return n.managers.some(function(x){ return x.m === m.name; }); })
          .map(function(n){ return tradeAngle['trade:' + n.gid]; })
          .filter(function(a){ return a !== undefined; });
        var sx = 0, sy = 0;
        angles.forEach(function(a){ sx += Math.cos(a); sy += Math.sin(a); });
        m._meanAngle = angles.length ? Math.atan2(sy, sx) : 0;
      });
      otherManagers.sort(function(a,b){ return a._meanAngle - b._meanAngle; });

      var mgrAngleStep = (2 * Math.PI) / Math.max(otherManagers.length, 1);
      otherManagers.forEach(function(n, i){
        var angle = -Math.PI/2 + i * mgrAngleStep;
        targets[n.id] = { x: cx + mgrRadius*Math.cos(angle), y: cy + mgrRadius*Math.sin(angle) };
      });

      sim.stop();
      var duration = 700;
      var starts = graphNodes.map(function(n){ return { n: n, x: n.x, y: n.y }; });
      var timer = d3.timer(function(elapsed){
        var t = Math.min(elapsed / duration, 1);
        var e = d3.easeCubicInOut(t);
        starts.forEach(function(s){
          var target = targets[s.n.id];
          if (!target) return;
          s.n.x = s.x + (target.x - s.x) * e;
          s.n.y = s.y + (target.y - s.y) * e;
        });
        linkSel.attr('x1', function(d){return d.source.x;}).attr('y1', function(d){return d.source.y;})
               .attr('x2', function(d){return d.target.x;}).attr('y2', function(d){return d.target.y;});
        nodeGroup.attr('transform', function(d){ return 'translate('+d.x+','+d.y+')'; });
        if (t >= 1) {
          timer.stop();
          graphNodes.forEach(function(n){ var tgt = targets[n.id]; if (tgt) { n.fx = tgt.x; n.fy = tgt.y; } });
        }
      });
    }

    if (explorerState.managerA !== 'any') {
      centerExplorerOn(explorerState.managerA);
    }

    // Escape hatch back to fully free-form physics.
    window.resetExplorerLayout = function(){
      graphNodes.forEach(function(n){ n.fx = null; n.fy = null; });
      sim.alpha(1).restart();
    };
  }


  var tradesSortState = { key: 'quad', type: 'number', dir: 'desc' };
  var tradesSeasonFilter = 'all';
  var tradesManagerFilter = 'all';

  function renderTradesSeasonPills() {
    var el = document.getElementById('trades-season-pills');
    var seasons = [...new Set(TRADES.map(function(t){return t.s;}))].sort();
    var html = '<button class="heatmap-season-pill active" onclick="setTradesSeasonFilter(\'all\', this)">All Seasons</button>';
    seasons.forEach(function(s) {
      var swatch = SEASON_COLORS[s] ? ' color-swatch-btn" style="--swatch-color:' + SEASON_COLORS[s] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setTradesSeasonFilter('+s+', this)">'+s+'</button>';
    });
    el.innerHTML = html;
  }

  function setTradesSeasonFilter(season, btn) {
    tradesSeasonFilter = season;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTradesTable();
  }

  function renderTradesManagerPills() {
    var el = document.getElementById('trades-manager-pills');
    if (!el) return;
    var managers = [...new Set(TRADES.map(function(t){return t.m;}))].sort();
    var html = '<button class="heatmap-season-pill active" onclick="setTradesManagerFilter(\'all\', this)">All Managers</button>';
    managers.forEach(function(m) {
      var swatch = MANAGER_COLORS[m] ? ' color-swatch-btn" style="--swatch-color:' + MANAGER_COLORS[m] + ';' : '';
      html += '<button class="heatmap-season-pill'+swatch+'" onclick="setTradesManagerFilter(\''+m+'\', this)">'+m+'</button>';
    });
    el.innerHTML = html;
  }

  function setTradesManagerFilter(manager, btn) {
    tradesManagerFilter = manager;
    btn.parentElement.querySelectorAll('.heatmap-season-pill').forEach(function(p){ p.classList.remove('active'); });
    btn.classList.add('active');
    renderTradesTable();
  }

  function renderTradesTable() {
    var tbody = document.querySelector('#trades-table tbody');
    var data = TRADES;
    if (tradesSeasonFilter !== 'all') data = data.filter(function(t){ return t.s === tradesSeasonFilter; });
    if (tradesManagerFilter !== 'all') data = data.filter(function(t){ return t.m === tradesManagerFilter; });
    var rows = sortRows(data, tradesSortState.key, tradesSortState.type, tradesSortState.dir);

    var html = '';
    rows.forEach(function(d, i){
      var quadBg = gradientColor(d.quad, QUAD_SCALE.min, QUAD_SCALE.max, true);
      var tgBg = gradientColor(d.tg, TG_SCALE.min, TG_SCALE.max, true);
      var rgBg = gradientColor(d.rg, RG_SCALE.min, RG_SCALE.max, true);
      var fitBg = gradientColor(d.fit, FIT_SCALE.min, FIT_SCALE.max, true);
      var necBg = d.nec === null ? null : gradientColor(d.nec, NEC_SCALE.min, NEC_SCALE.max, true);
      var necDisplay = d.nec === null ? '&ndash;' : d.nec.toFixed(1);
      var seasonColor = SEASON_COLORS[d.s] || 'var(--muted)';
      html += '<tr>'
        +'<td class="tv-rank">'+(i+1)+'</td>'
        +'<td><span class="season-pill" style="background:'+seasonColor+';">'+d.s+'</span>'+(d.multi ? '<span class="multi-badge">MULTI</span>' : '')+'</td>'
        +'<td>Wk '+d.wk+'</td>'
        +'<td style="font-weight:600;color:var(--palm)">'+d.m+'</td>'
        +'<td class="got-txt">'+d.got.join(', ')+'</td>'
        +'<td class="gave-txt">'+d.gave.join(', ')+'</td>'
        +'<td><span style="background:'+tgBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.tg.toFixed(1)+'</span></td>'
        +'<td><span style="background:'+rgBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.rg.toFixed(1)+'</span></td>'
        +'<td><span style="background:'+fitBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.fit.toFixed(2)+'</span></td>'
        +'<td>'+(necBg ? '<span style="background:'+necBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+necDisplay+'</span>' : necDisplay)+'</td>'
        +'<td><span style="background:'+quadBg+';color:#fff;padding:0.15rem 0.5rem;border-radius:4px;font-weight:700;">'+d.quad.toFixed(2)+'</span></td>'
        +'</tr>';
    });
    tbody.innerHTML = html;
  }

  renderQuadPills();
  renderQuadMetricToggle();
  try {
    renderQuadChart();
  } catch (e) {
    console.error('QUAD chart failed to render:', e);
    var chartCard = document.getElementById('chart-quad');
    if (chartCard && chartCard.parentElement) {
      chartCard.parentElement.innerHTML = '<p class="metric-note">Chart failed to load. Table data below is unaffected.</p>';
    }
  }
  try {
    renderWinPct();
  } catch (e) {
    console.error('Win% chart failed to render:', e);
  }
  try {
    renderNetwork();
  } catch (e) {
    console.error('Trade network failed to render:', e);
    var netContainer = document.getElementById('network-container');
    if (netContainer) netContainer.innerHTML = '<p class="metric-note">Network graph failed to load.</p>';
  }
  try {
    renderMostTradedPosPills();
    renderMostTraded();
  } catch (e) {
    console.error('Most traded chart failed to render:', e);
  }
  try {
    renderTradeWeekFilters();
    renderTradeWeekChart();
  } catch (e) {
    console.error('Trades by week chart failed to render:', e);
    var twCard = document.getElementById('chart-trade-week');
    if (twCard && twCard.parentElement) {
      twCard.parentElement.innerHTML = '<p class="metric-note">Chart failed to load.</p>';
    }
  }
  try {
    renderExplorerFilters();
    renderExplorer();
  } catch (e) {
    console.error('Trade Explorer failed to render:', e);
    var expContainer = document.getElementById('explorer-container');
    if (expContainer) expContainer.innerHTML = '<p class="metric-note">Trade Explorer failed to load.</p>';
  }
  renderTradesSeasonPills();
  renderTradesManagerPills();
  renderTradesTable();
  wireSortableHeaders('trades-table', renderTradesTable, tradesSortState);


  // the handlers the page's markup names (inline onclick, as on the Stage A page)
  Object.assign(window, { resetExplorerLayout, resetNetworkLayout, setMostTradedPosFilter, setQuadFilter, setQuadMetric, setTradeWeekSeason, setTradesManagerFilter, setTradesSeasonFilter });
}

config().then(function (c) {
  cfg = c;
  mgr = managers(cfg);
  drawNav(cfg, 'trade-value');
  drawSubnav(cfg, 'trade-value');
  drawFooter(cfg);
  chapterRail();
  return load('data/v1/trade-value.json');
}).then(function (M) {
  var D = tradeData(M, mgr.name);
  PAGE_SEASONS = D.PAGE_SEASONS; LEADERBOARD = D.LEADERBOARD; LEADERBOARD_TOTALS = D.LEADERBOARD_TOTALS;
  BEST_WORST = D.BEST_WORST; TRADES = D.TRADES; QUAD_SCALE = D.QUAD_SCALE; TG_SCALE = D.TG_SCALE; RG_SCALE = D.RG_SCALE;
  FIT_SCALE = D.FIT_SCALE; NEC_SCALE = D.NEC_SCALE; NETWORK_DATA = D.NETWORK_DATA; WINPCT_DATA = D.WINPCT_DATA;
  TRADE_NODES = D.TRADE_NODES; TRADE_WEEK_DATA = D.TRADE_WEEK_DATA; MOST_TRADED = D.MOST_TRADED;
  PAGE_LIVE_SEASON = cfg.live_season != null && PAGE_SEASONS.indexOf(cfg.live_season) !== -1 ? cfg.live_season : null;
  SEASON_COLORS = (cfg.theme && cfg.theme.season_colors) || {};
  MANAGER_COLORS = {};
  mgr.visible.forEach(function (m) { if (m.colors) MANAGER_COLORS[m.name] = m.colors.dark; });
  methodNotes(cfg, mgr, PAGE_SEASONS);
  leagueNotes(M);
  runPage();
}).catch(function (err) {
  console.error(err);
  var el = document.querySelector('#trades-table tbody');
  if (el) el.innerHTML = '<tr><td colspan="11"><div class="data-state data-state-error">This page could not be loaded.</div></td></tr>';
});
