export function BrandMark() {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- статичный маленький PNG, next/image требует sharp в проде (не установлен), не стоит того ради логотипа
    <img src="/brand/logo-master.png" alt="Логотип платформы" width={462} height={329} className="h-7 w-auto" />
  );
}
