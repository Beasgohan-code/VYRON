import type { ReactNode } from "react";

interface Props {
  title: string;
  icon?: ReactNode;
  tag?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, icon, tag, action, children, className = "" }: Props) {
  return (
    <article className={`panel ${className}`}>
      <div className="panel-head">
        <h3>
          {icon}
          {title}
        </h3>
        {tag}
        {action}
      </div>
      {children}
    </article>
  );
}

export function SectionHead({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="section-head">
      <h2>{children}</h2>
      {right}
    </div>
  );
}
