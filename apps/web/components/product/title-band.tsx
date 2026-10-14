import { PageContainer } from '@/components/product/page-container';

export type TitleBandProps = {
  title: string;
  description: string;
  breadcrumb: string;
  variant?: 'default' | 'tall';
};

export function TitleBand({ title, description, breadcrumb, variant = 'default' }: TitleBandProps) {
  return (
    <section className={`app-title-band ${variant === 'tall' ? 'app-title-band-tall' : ''}`}>
      <PageContainer className="flex flex-col items-center gap-2 text-center" aria-label={breadcrumb}>
        <h1 className="text-[28px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">{title}</h1>
        <p className="max-w-[70ch] text-[14.5px] leading-[1.7] text-[var(--product-muted)]">{description}</p>
      </PageContainer>
    </section>
  );
}
