import { BrandPage } from "./_components/BrandPage";

export default async function Page({ params }: { params: Promise<{ brandSlug: string }> }) {
  const { brandSlug } = await params;
  return <BrandPage brandId={brandSlug} />;
}
