export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 7 15 10V28L3 25Z" fill="#5B93D6" />
      <path d="M29 7 17 10V28L29 25Z" fill="#2F6FB8" />
      <path d="M19.5 17.5 22 20l4.5-6" fill="none" stroke="#E8F0FA" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
