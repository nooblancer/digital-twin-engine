export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-[1920px] px-4 py-4 sm:px-6 lg:px-8">
      {children}
    </div>
  );
}
