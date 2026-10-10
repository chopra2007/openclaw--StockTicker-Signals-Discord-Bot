"""Approved collection and explicit public projections; no bot wrapper calls."""
import asyncio
from dataclasses import replace
import math
from .contracts import (SectionResult, SecPayload, Filing, InsiderSummary, Metric,
    OptionsPayload, OptionContract, MovePayload, MoveRange, QuoteTime, Evidence,
    AnalysisPayload, Level, ContextMetric, Horizon, Quote, Chart)
from .providers import ProviderContext, ProviderSpec, ResearchCompletion
from .sec_notices import notice_summary, person_name, canonical_notice_name


def metric(value, unit, method):
    if value is not None and (isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value)):
        raise ValueError('Finite numeric values required')
    return Metric(value=float(value) if value is not None else None,unit=unit,method=method)



SEC_LOOKBACK_HOURS,SEC_MAX_FILINGS,SEC_MAX_CANDIDATES=90*24,15,100
FORM_TITLES={'8-K':'Major company event','10-K':'Annual report','10-Q':'Quarterly report','4':'Insider trade',
             '144':'Planned insider sale','SC 13D':'Large stake (activist)','SC 13G':'Large stake (passive)'}
FORM_NOTES={'8-K':'Filed for news such as earnings, deals or leadership changes.','10-K':'Full-year results and risks.',
            '10-Q':'Quarterly results.','144':'An insider notified the SEC of a planned share sale.',
            'SC 13D':'An investor owns over 5% and may push for changes.','SC 13G':'An investor owns over 5% as a passive holder.'}


def _insider_line(detail):
    """'Jane Doe (CFO) sold 12,000 shares for $1.4M' from a Form 4, or a plain fallback."""
    rows=detail.data if detail is not None and detail.status in ('ok','partial') and detail.data else ()
    if not rows: return 'Insider transaction details unavailable.'
    first=rows[0]
    name=person_name(first.reporter_name,last_first=True)
    trades=[r for r in rows if r.transaction_type in ('Open Market Purchase','Open Market Sale')]
    if trades:
        parts=[]
        for kind,verb in [('Open Market Purchase','bought'),('Open Market Sale','sold')]:
            selected=[r for r in trades if r.transaction_type==kind]
            if not selected: continue
            shares=sum(r.shares or 0 for r in selected); value=sum((r.shares or 0)*(r.price or 0) for r in selected)
            amount=f' for ${value/1e6:,.1f}M' if value>=1e6 else f' for ${value:,.0f}' if value else ''
            parts.append(f'{verb} {shares:,.0f} shares{amount}')
        return f'{name} ({first.title}) {" and ".join(parts)} on the open market.'
    kinds=sorted({r.transaction_type.lower() for r in rows if r.transaction_type!='Unknown'})
    return f'{name} ({first.title}): routine {", ".join(kinds) or "transaction"}, not an open-market trade.'

def _usd(value):
    for size,unit in ((1e9,'B'),(1e6,'M'),(1e3,'K')):
        if value>=size: return f'${value/size:.1f}{unit}'
    return f'${value:,.0f}'


def insider_totals(payload):
    """'4 insiders sold $71.4M on the open market in the last 90 days.' from the SEC section's Form 4 rows
    (same counting as the SEC card). None when the details are incomplete and nothing was found."""
    buyers,sellers,bought,sold=set(),set(),0.0,0.0
    for row in payload.insiders:
        if row.conviction!='conviction': continue
        name=(row.reporter_name or row.accession).strip().lower()
        if row.bought_value and row.bought_value.value: buyers.add(name); bought+=row.bought_value.value
        if row.sold_value and row.sold_value.value: sellers.add(name); sold+=row.sold_value.value
    part=lambda people,verb,amount:f'{len(people)} insider{"" if len(people)==1 else "s"} {verb} {_usd(amount)}'
    parts=[part(buyers,'bought',bought) if bought else None,part(sellers,'sold',sold) if sold else None]
    parts=[p for p in parts if p]
    partial=payload.coverage!='complete'
    if not parts: return None if partial else 'No open-market insider trades in the last 90 days.'
    return '; '.join(parts)+' on the open market in the last 90 days'+(' (some filings could not be read).' if partial else '.')


class MemberResearchProvider:
    def __init__(self, context):
        if not isinstance(context,ProviderContext): raise ValueError('Explicit provider context required')
        self.context=context
        self._form4_details={}
        self._event_details={}
        self._notice_details={}

    def register(self, registry):
        for section,lineage in self.context.lineage.items():
            asynchronous=section in ('sec','analysis')
            registry.register(section,ProviderSpec(lineage,self.compute if asynchronous else self.compute_blocking,
                              self.context.primary_source,asynchronous,analysis_version='member-research-v1'))

    def _authorize(self, section, use='display_derived', observed_at=None):
        lineage=self.context.lineage[section]
        mixed=any(key.startswith('analysis_') if section=='analysis' else key.startswith('supplied_metrics.'+section+'.') for key in self.context.input_dependencies)
        if mixed or hasattr(self.context.policy,'store'):
            from .features import require_features
            with self.context.policy.store.transaction() as con:
                if not require_features(con,lineage.required_features): raise ValueError('feature_unavailable')
        decision=self.context.policy.authorize_lineage(lineage,use,self.context.clock().timestamp(),observed_at=observed_at)
        if not decision.allowed: raise ValueError('source_permission_unavailable')
        return lineage

    def _result(self,section,payload=None,message=None,*,observed_at=None,evidence=()):
        if payload is not None and hasattr(payload,'context_metrics'):
            from consensus_engine.analysis.research_contracts import DerivedContextMetric
            from .contracts import ContentLineage
            lineage=self.context.lineage[section]
            values=[]
            for row in (self.context.supplied_metrics or {}).get(section,()):
                if type(row) is not DerivedContextMetric: continue
                sources=[source for source in lineage.sources if source.source_id==row.source_id and source.source_version==row.source_version]
                if len(sources)!=1: continue
                specific=lineage.model_copy(update={'sources':sources})
                if not all(self.context.policy.authorize_lineage(specific,use,self.context.clock().timestamp(),observed_at=row.observed_at).allowed for use in ('retain','display_raw','display_derived')):
                    continue
                values.append(ContextMetric(name=row.name,metric=metric(row.value,row.unit,row.method),
                                            observed_at=row.observed_at,source_id=row.source_id,source_version=row.source_version))
            payload=payload.model_copy(update={'context_metrics':values[:20]})
        return SectionResult(section=section,status='completed' if payload is not None else 'unavailable',
            job_id=None,result_id=None,observed_at=observed_at,computed_at=self.context.clock().timestamp(),
            valid_until=None,stale=False,analysis_version='member-research-v1',payload=payload,
            evidence=list(evidence),message=message)

    async def compute(self,ticker,section,inputs):
        try:
            self._authorize(section,'retain')
            if section == 'sec': return await self._sec(ticker)
            if section == 'analysis': return await self._analysis(ticker,inputs)
            return self.compute_blocking(ticker,section,inputs)
        except Exception:
            self.context.telemetry({'event':'member_collection_unavailable','reason_code':'collection_unavailable'})
            return self._result(section,message='collection_unavailable')

    async def _sec(self,ticker):
        from consensus_engine.analysis.sec_research import collect_sec
        from consensus_engine.scanners.sec_edgar import fetch_filings_outcome,fetch_form4_outcome,fetch_filing_document_outcome
        from .sec_events import event_summary
        context=self.context.sec_context
        if context is None or getattr(context,'bot_compat',False): raise ValueError('isolated_sec_context_required')
        from consensus_engine.utils.provider_budget import BudgetSession
        if not isinstance(context.client,BudgetSession): raise ValueError('budgeted_sec_client_required')
        async def filings(ticker,hours):
            # Owner report 2026-10-06: 72 hours left NVDA/MU empty. Show the newest filings of the last 90 days.
            self._authorize('sec','retain')
            outcome=await fetch_filings_outcome(ticker,SEC_LOOKBACK_HOURS,context)
            if not outcome.data: return outcome
            candidates=tuple(sorted(outcome.data,key=lambda row:row.filed_at,reverse=True))
            return replace(outcome,data=candidates[:SEC_MAX_CANDIDATES],
                           status='partial' if len(candidates)>SEC_MAX_CANDIDATES else outcome.status,
                           reason_code='filing_scan_limit' if len(candidates)>SEC_MAX_CANDIDATES else outcome.reason_code)
        async def detail(cik,accession,document):
            self._authorize('sec','retain')
            key=(cik,accession,document)
            if key in self._form4_details: return self._form4_details[key]
            result=await fetch_form4_outcome(cik,accession,document,context)
            if result.status=='ok':
                if len(self._form4_details)>=256: self._form4_details.pop(next(iter(self._form4_details)))
                self._form4_details[key]=result
            return result
        research=await collect_sec(ticker,filings,detail)
        outcome=research.filings
        if outcome.status not in ('ok','partial'):
            return self._result('sec',message=outcome.reason_code,observed_at=outcome.observed_at)
        self._authorize('sec',observed_at=outcome.observed_at)
        details={item.accession:item.outcome for item in research.details}
        owner_names=[tx.reporter_name for detail in details.values() if detail.status in ('ok','partial') for tx in (detail.data or ())]
        filings,insiders=[],[]
        coverage=research.coverage
        for row in outcome.data:
            event=None
            notice=None
            if row.form=='144':
                self._authorize('sec','retain')
                key=(row.cik,row.accession_number,row.primary_document)
                notice=self._notice_details.get(key)
                if notice is None:
                    document=await fetch_filing_document_outcome(*key,context)
                    notice=notice_summary(document.data) if document.status=='ok' else None
                    if notice:
                        if len(self._notice_details)>=128: self._notice_details.pop(next(iter(self._notice_details)))
                        self._notice_details[key]=notice
                if not notice:
                    coverage='partial'
                    continue
                notice=canonical_notice_name(notice,owner_names)
            if row.form=='8-K':
                self._authorize('sec','retain')
                key=(row.cik,row.accession_number,row.primary_document)
                event=self._event_details.get(key)
                if event is None:
                    document=await fetch_filing_document_outcome(*key,context)
                    event=event_summary(document.data) if document.status=='ok' else None
                    if event:
                        if len(self._event_details)>=128: self._event_details.pop(next(iter(self._event_details)))
                        self._event_details[key]=event
                if not event:
                    coverage='partial'
                    continue
            detail=details.get(row.accession_number)
            status='ok' if row.form != '4' or detail and detail.status == 'ok' else 'unavailable' if detail else 'not_requested'
            filings.append(Filing(accession=row.accession_number,form=row.form,filed_at=row.filed_at,
                title=event[0] if event else FORM_TITLES.get(row.form,row.form),summary=notice or (event[1] if event else _insider_line(detail) if row.form=='4' else FORM_NOTES.get(row.form,'')),
                url=row.url,detail_status=status))
            if row.form == '4':
                transactions=detail.data if detail and detail.status in ('ok','partial') else ()
                conviction=any(tx.transaction_type in ('Open Market Purchase','Open Market Sale') for tx in transactions)
                complete=detail is not None and detail.status == 'ok'
                routine=complete and bool(transactions) and all(tx.transaction_type in
                    ('Award/Grant','Tax Withholding','Option Exercise','Gift','Disposition') for tx in transactions)
                label='conviction' if conviction else 'routine' if routine else 'unknown'
                amount=sum(tx.shares*tx.price for tx in transactions if tx.transaction_type in ('Open Market Purchase','Open Market Sale') and tx.shares is not None and tx.price is not None)
                value=metric(amount,'USD','verified open-market shares times price') if complete and conviction else None
                def side_value(kind):
                    selected=[tx for tx in transactions if tx.transaction_type==kind]
                    return metric(sum(tx.shares*tx.price for tx in selected),'USD','verified open-market shares times price') if complete and selected else None
                insiders.append(InsiderSummary(accession=row.accession_number,summary={'conviction':'Open-market transaction reported.','routine':'Routine transactions reported.','unknown':'Insider detail coverage incomplete.'}[label],conviction=label,transaction_value=value,
                    reporter_name=person_name(transactions[0].reporter_name,last_first=True) if transactions else None,
                    bought_value=side_value('Open Market Purchase'),sold_value=side_value('Open Market Sale')))
                if routine:
                    filings.pop()
        warning='Filing or insider detail coverage is incomplete.' if coverage == 'partial' else None
        message='No non-routine filings in the last 90 days.' if not filings and coverage == 'complete' else warning if not filings else None
        return self._result('sec',SecPayload(coverage=coverage,filings=filings[:SEC_MAX_FILINGS],insiders=insiders,warning=warning),
                            message,observed_at=outcome.observed_at)

    def _chain(self,ticker,section,source,nearest):
        self._authorize(section,'retain')
        lineage=self.context.lineage[section]
        if source not in {item.source_id for item in lineage.sources}: raise ValueError('untracked_source')
        client=self.context.clients[source]
        chain=client.get_option_chain(ticker,nearest=nearest)
        if chain is None: raise ValueError('chain_unavailable')
        return client,chain

    @staticmethod
    def _strict_chain(chain, *, em=False):
        """Reject malformed/nonfinite values; optional missing OI remains missing."""
        for frame in (chain.calls,chain.puts):
            if frame is None: raise ValueError('missing_chain_side')
            if len(frame)>100_000: raise ValueError('chain_too_large')
            for row in frame.to_dict('records'):
                for field in ('strike','bid','ask','lastPrice','volume','openInterest','impliedVolatility'):
                    value=row.get(field)
                    if value is None:
                        if field in ('strike','volume') or not em and field=='lastPrice' or em and field in ('bid','ask','openInterest'):
                            raise ValueError('missing_required_quote')
                        continue
                    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                        raise ValueError('invalid_quote')

    def _observations(self, section, values, *, milliseconds=False):
        """Authorize real source observations, independently of last-trade time."""
        epochs=[]
        now=self.context.clock().timestamp()
        for value in values:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('missing_source_observation')
            epoch=value/1000 if milliseconds else value
            if not 0 < epoch <= now: raise ValueError('invalid_source_observation')
            epochs.append(epoch)
        # Equal timestamps share the same policy decision; every row was validated.
        for epoch in set(epochs): self._authorize(section,observed_at=epoch)
        return epochs

    def compute_blocking(self,ticker,section,inputs):
        """Register on the existing runtime's blocking lane, including rendering."""
        try:
            self._authorize(section,'retain')
            if section=='options': return self._options(ticker)
            if section in ('em_daily','em_weekly'): return self._move(ticker,section)
            raise ValueError('unsupported_section')
        except Exception:
            self.context.telemetry({'event':'member_collection_unavailable','reason_code':'collection_unavailable'})
            return self._result(section,message='collection_unavailable')

    def _options(self,ticker):
        from consensus_engine.scanners.options import _detect_unusual_activity,_scan_chain_for_flow
        from consensus_engine.analysis.options_presentation import select_options
        from types import SimpleNamespace
        chain=None
        for source in (self.context.primary_source,*self.context.fallback_allowlist):
            try:
                _,candidate=self._chain(ticker,'options',source,2)
                self._strict_chain(candidate)
                chain=candidate
                break
            except Exception:
                self.context.telemetry({'event':'member_options_unavailable','reason_code':'options_collection_unavailable'})
        if chain is None: return self._result('options',message='options_collection_unavailable')
        # Internal legacy arithmetic treats absent OI as ineligible, while public
        # missingness is retained by omitting these contracts from the ratio pool.
        def owned(frame):
            result=frame.copy()
            if 'openInterest' in result: result['openInterest']=result['openInterest'].fillna(0)
            return result
        import pandas as pd
        selected_chains=[chain.by_expiry(expiry) for expiry in chain.expirations[:2]]
        calculated=SimpleNamespace(
            calls=pd.concat([owned(part.calls) for part in selected_chains],ignore_index=True) if selected_chains else chain.calls.iloc[:0],
            puts=pd.concat([owned(part.puts) for part in selected_chains],ignore_index=True) if selected_chains else chain.puts.iloc[:0])
        result=_detect_unusual_activity(calculated)
        now=self.context.clock().timestamp()
        hits=[]
        spot=chain.underlying_price
        if spot is not None and (not math.isfinite(spot) or spot<0): raise ValueError('invalid_spot')
        for expiry in chain.expirations[:2]:
            sub=chain.by_expiry(expiry)
            hits.extend(_scan_chain_for_flow(ticker,SimpleNamespace(calls=owned(sub.calls),puts=owned(sub.puts)),expiry,
                spot or 0,min_vol_oi=.01,min_volume=100,min_premium=0,max_stale_sec=0,now=now,staleness_failclosed=False))
        selected=select_options(result,hits)
        contracts=[OptionContract(symbol=hit.contract_symbol,expiry=hit.expiry,side=hit.side.lower(),
            strike=metric(hit.strike,'USD','listed strike'),volume=metric(hit.volume,'contracts','reported option volume'),
            open_interest=metric(hit.open_interest,'contracts','reported open interest'),
            premium=metric(hit.premium_usd,'USD','last price times volume times 100'),
            observed_at=hit.last_trade_ts or None) for hit in sorted(selected.eligible,key=lambda hit:hit.vol_oi_ratio,reverse=True)[:200]]
        observation=max((item.observed_at for item in contracts if item.observed_at is not None),default=None)
        self._authorize('options',observed_at=observation)
        payload=OptionsPayload(contracts=contracts,call_volume=metric(result.total_call_vol,'contracts','two-expiration reported call volume'),
            put_volume=metric(result.total_put_vol,'contracts','two-expiration reported put volume'),
            put_call_ratio=metric(selected.put_call_ratio,'ratio','put volume divided by call volume'),call_premium=None,put_premium=None)
        contribution=next(row for row in self.context.lineage['options'].sources if row.source_id==source)
        evidence=(Evidence(id='options-collection',source_id=source,source_version=contribution.source_version,
                           observed_at=observation,url=None,excerpt='Two nearest expirations; reported option activity.',research_only=True),)
        return self._result('options',payload,'No eligible unusual activity.' if not contracts else None,
                            observed_at=observation,evidence=evidence)

    def _move(self,ticker,section):
        import pandas as pd
        from consensus_engine.scanners.expected_move import compute_em_from_bundle,select_expiration
        horizon='daily' if section=='em_daily' else 'weekly'
        now=self.context.clock()
        result=None
        for source in (self.context.primary_source,*self.context.fallback_allowlist):
            try:
                client,chain=self._chain(ticker,section,source,8)
                self._strict_chain(chain,em=True)
                spot=chain.underlying_price
                if spot is None or not math.isfinite(spot) or spot<=0: raise ValueError('missing_spot')
                from zoneinfo import ZoneInfo
                expiry,label=select_expiration(chain.expirations,now.astimezone(ZoneInfo('America/New_York')),horizon)
                chosen=chain.by_expiry(expiry)
                bundle=dict(spot=spot,expiration=expiry,session_label=label,calls=chosen.calls,puts=chosen.puts,
                            history=pd.DataFrame(),history_label='no price history',source=source)
                candidate=compute_em_from_bundle(ticker,bundle,self.context.settings,now,horizon)
                times=[]
                selection=[]
                for kind,frame,quote in (('call',chosen.calls,candidate.call),('put',chosen.puts,candidate.put)):
                    epochs=self._observations(section,frame.get('providerQuoteTime',[None]*len(frame)),milliseconds=True)
                    if not epochs: raise ValueError('missing_source_observation')
                    selection.extend(epochs)
                    index=next(i for i,strike in enumerate(frame['strike']) if strike==quote.strike)
                    times.append(QuoteTime(source_id=source,input_kind=kind,observed_at=epochs[index]))
                spot_time=self._observations(section,[getattr(chain,'underlying_quote_time',None)])[0]
                times.extend((QuoteTime(source_id=source,input_kind='underlying',observed_at=spot_time),
                              QuoteTime(source_id=source,input_kind='selection',observed_at=max(selection))))
                result=candidate
                break
            except Exception:
                self.context.telemetry({'event':'member_quote_unavailable','reason_code':'quote_quality_unavailable'})
        if result is None: return self._result(section,message='quote_quality_unavailable')
        attempts=[('1mo','1d'),('3mo','1d'),('10d','15m')] if horizon=='weekly' else [('5d','5m'),('10d','15m'),('3mo','1d')]
        for period,interval in attempts:
            try:
                self._authorize(section,'retain')
                history=client.get_price_history(ticker,period=period,interval=interval)
                if history is not None and len(history)>=5:
                    if len(history)>10_000 or not all(math.isfinite(float(v)) for key in ('Open','High','Low','Close') for v in history[key]):
                        raise ValueError('invalid_history')
                    history_times=self._observations(section,history.get('sourceObservedAt',[None]*len(history)))
                    result.history=history
                    result.history_label=period+' / '+interval
                    times.append(QuoteTime(source_id=source,input_kind='history',observed_at=max(history_times)))
                    break
            except Exception: pass
        observation=max(item.observed_at for item in times)
        self._authorize(section,observed_at=observation)
        ranges=[MoveRange(method='raw ATM straddle',lower=metric(result.lower,'USD','spot minus straddle'),
                    upper=metric(result.upper,'USD','spot plus straddle'),expected_move=metric(result.primary_em,'USD','call midpoint plus put midpoint'))]
        if result.iv_band_lower is not None:
            ranges.append(MoveRange(method='ATM implied volatility one standard deviation',
                lower=metric(result.iv_band_lower,'USD','spot minus IV move'),upper=metric(result.iv_band_upper,'USD','spot plus IV move'),
                expected_move=metric(result.em['iv_em_1sd'],'USD','ATM IV and time to selected expiry')))
        payload=MovePayload(horizon=horizon,spot=metric(result.spot,'USD','chain underlying quote'),expiry=result.expiration,
            ranges=ranges,quote_times=times,chart_asset_id=None)
        public=self._result(section,payload,observed_at=observation)
        png=None
        if self.context.chart_renderer is not None:
            try:
                png=self.context.chart_renderer(result)
                if png is not None:
                    from .assets import validate_png
                    validate_png(png)
            except Exception:
                png=None
                self.context.telemetry({'event':'member_chart_unavailable','reason_code':'chart_unavailable'})
        return ResearchCompletion(public,png)

    async def _analysis(self,ticker,inputs):
        allowed=inputs.get('enabled_features')
        if not isinstance(allowed,list) or not set(self.context.lineage['analysis'].required_features)<=set(allowed):
            raise ValueError('feature_unavailable')
        from consensus_engine.analysis.research_compute import MemberResearchProvider as PureProvider
        from .market_reader import safe_url
        services,records=self.context.analysis_services,self.context.analysis_records
        collector=self.context.analysis_collector
        if collector is None and (services is None or records is None): raise ValueError('analysis_records_unavailable')
        def approved(rows,use):
            lineage=self.context.lineage['analysis']
            tracked={(source.source_id,source.source_version) for source in lineage.sources}
            if any((row.source_id,row.source_version) not in tracked for row in rows):
                raise ValueError('untracked_evidence')
            for row in rows:
                self._authorize('analysis',use,observed_at=row.observed_at)
        if collector is not None: return await self._study(ticker,collector,approved)
        record=records[ticker]
        approved(record.evidence,'retain')
        async def synthesis(request):
            approved(request.evidence,'model_input')
            self._authorize('analysis','model_input',observed_at=min((row.observed_at for row in request.evidence if row.observed_at is not None),default=None))
            response=await services.synthesis(request)
            self._authorize('analysis','model_input',observed_at=min((row.observed_at for row in request.evidence if row.observed_at is not None),default=None))
            return response
        async def gap(request):
            self._authorize('analysis','model_input')
            response=await services.gap_fill(request)
            self._authorize('analysis','model_input')
            approved(response.evidence,'retain')
            return response
        result=await PureProvider(records,replace(services,synthesis=synthesis,gap_fill=gap)).compute(ticker)
        observed=min((item.observed_at for item in result.evidence if item.observed_at is not None),default=None)
        self._authorize('analysis',observed_at=observed)
        structured=result.structured
        levels=[Level(label=name,price=metric(getattr(structured,name),'USD','shared research trade plan'))
                for name in ('sl','tp1','tp2','tp3','buy_zone_low','buy_zone_high') if getattr(structured,name,None) is not None]
        payload=AnalysisPayload(summary=result.narrative[:4000],direction=structured.direction.lower(),score=metric(result.score_breakdown.total,'points','shared additive research score'),
                                conflicts=list(result.conflicts),levels=levels)
        approved(result.evidence,'display_raw')
        from .news import article_url
        evidence=[Evidence(id=row.id,source_id=row.source_id,source_version=row.source_version,observed_at=row.observed_at,
                           url=article_url(row.url) if row.id.startswith('news-') else safe_url(row.url),excerpt=row.excerpt[:4000],research_only=row.research_only) for row in result.evidence[:200]]
        return self._result('analysis',payload,observed_at=observed,evidence=evidence)

    async def _study(self,ticker,collector,approved):
        """Owner 2026-10-06: news catalysts, a week/month/year outlook and a reason for every level."""
        from .market_reader import safe_url
        from .news import article_url
        async def write(request):
            approved(request.evidence,'model_input')
            self._authorize('analysis','model_input',observed_at=min((row.observed_at for row in request.evidence if row.observed_at is not None),default=None))
            response=await collector.synthesis(request)
            self._authorize('analysis','model_input',observed_at=min((row.observed_at for row in request.evidence if row.observed_at is not None),default=None))
            return response
        async def insiders():
            """Owner 2026-10-06 (TODO #121 item 6): the write-up names insider buying/selling; it runs beside the market reads."""
            try:
                section=await asyncio.wait_for(self._sec(ticker),30)
                if not isinstance(section.payload,SecPayload): return None
                self._authorize('sec','model_input')
                return insider_totals(section.payload)
            except Exception: return None  # The write-up goes ahead without it.
        study=await collector.study(ticker,write=write,chart=True,insiders=asyncio.ensure_future(insiders()))
        approved(study.evidence,'retain')
        result,facts=study.result,study.facts
        observed=min((item.observed_at for item in result.evidence if item.observed_at is not None),default=None)
        self._authorize('analysis',observed_at=observed)
        usd=lambda value:metric(value,'USD','member trade map')
        levels,horizons=[],[]
        plan=(facts or {}).get('trade_plan')
        if plan:
            levels+=[Level(label='buy_zone_low',price=usd(plan['entry_low']),note=plan['entry_why']),
                     Level(label='buy_zone_high',price=usd(plan['entry_high'])),
                     Level(label='sl',price=usd(plan['stop']),note=plan['stop_why'])]
            levels+=[Level(label=f'tp{index}',price=usd(target['price']),note=target['why']) for index,target in enumerate(plan['targets'],1)]
        for row in (facts or {}).get('key_levels',[]):
            levels.append(Level(label=row['kind'],price=usd(row['price']),note=row['why']))
        if facts:
            for label,key in (('week','next_week_range'),('month','next_month_range')):
                r=facts['options'].get(key)
                if r: horizons.append(Horizon(label=label,low=usd(r['low']),high=usd(r['high']),
                                              note=f"Options price a {r['move_pct']}% move by {r['until']}."))
            ws=facts['wall_street']
            if ws.get('target_average'):
                ratings=', '.join(f'{ws[k]} {k}' for k in ('buy','hold','sell') if ws.get(k) is not None)
                horizons.append(Horizon(label='year',low=usd(ws.get('target_low')),high=usd(ws.get('target_high')),middle=usd(ws['target_average']),
                                        note='Wall Street price targets'+(f' ({ratings})' if ratings else '')+'.'))
        payload=AnalysisPayload(summary=study.note[:4000],direction=result.structured.direction.lower(),
                                score=metric(result.score_breakdown.total,'points','shared additive research score'),
                                conflicts=list(result.conflicts),levels=levels,horizons=horizons,
                                company=(study.display or {}).get('company'),
                                quote=Quote(**study.display['quote']) if study.display else None,
                                chart=Chart(**study.display['chart']) if study.display else None)
        approved(result.evidence,'display_raw')
        evidence=[Evidence(id=row.id,source_id=row.source_id,source_version=row.source_version,observed_at=row.observed_at,
                           url=article_url(row.url) if row.id.startswith('news-') else safe_url(row.url),excerpt=row.excerpt[:4000],research_only=row.research_only) for row in result.evidence[:200]]
        return self._result('analysis',payload,observed_at=observed,evidence=evidence)
