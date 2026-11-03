export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_480px]">
      <section className="hidden flex-col justify-between border-r border-rule p-12 lg:flex">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-md bg-marigold text-base font-black text-ink">M</span>
          <span className="text-lg font-bold tracking-tight">MarketingOS</span>
        </div>
        <div className="max-w-lg">
          <p className="text-[40px] font-extrabold leading-[1.05] tracking-tight">
            Your marketing team drafts. You sign off.
          </p>
          <p className="mt-4 text-[17px] leading-relaxed text-ink-2">
            Agents prepare posts, ads, SEO fixes and AI-search content for every brand you run. Nothing is published and no
            rupee is spent until someone on your team approves it.
          </p>
          <ol className="mt-8 space-y-3 text-[15px]">
            {[
              ["Drafted", "15 Instagram posts and a Meta campaign for November"],
              ["Checked", "brand voice, prohibited claims, platform limits"],
              ["Waiting for you", "₹30,000 budget over 30 days"],
            ].map(([k, v], i) => (
              <li key={k} className="flex items-baseline gap-3">
                <span className={i === 2 ? "rounded bg-marigold px-1.5 text-[13px] font-semibold" : "text-[13px] font-semibold text-leaf"}>{k}</span>
                <span className="text-ink-2">{v}</span>
              </li>
            ))}
          </ol>
        </div>
        <p className="text-xs text-faint">Built for small businesses and the agencies that run their marketing.</p>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">{children}</div>
      </section>
    </div>
  );
}
