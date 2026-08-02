'use client';

/**
 * shared/ui — 最小共享组件集
 * Card / FormField / ActionButton / PageShell / SectionHeader
 * 不引入外部 UI 库，纯 CSS 变量 + Tailwind 兼容样式。
 */

import React from 'react';

/* ── Card ───────────────────────────────────────────────────── */

interface CardProps {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  className?: string;
  headerRight?: React.ReactNode;
}

export function Card({ children, title, subtitle, className = '', headerRight }: CardProps) {
  return (
    <div className={`hevi-card ${className}`}>
      {(title || headerRight) && (
        <div className="hevi-card__header">
          <div>
            {title && <h3 className="hevi-card__title">{title}</h3>}
            {subtitle && <p className="hevi-card__subtitle">{subtitle}</p>}
          </div>
          {headerRight && <div className="hevi-card__actions">{headerRight}</div>}
        </div>
      )}
      <div className="hevi-card__body">{children}</div>
    </div>
  );
}

/* ── FormField ──────────────────────────────────────────────── */

interface FormFieldProps {
  label: string;
  children: React.ReactNode;
  hint?: string;
  required?: boolean;
  className?: string;
}

export function FormField({ label, children, hint, required, className = '' }: FormFieldProps) {
  return (
    <div className={`hevi-field ${className}`}>
      <label className="hevi-field__label">
        {label}
        {required && <span className="hevi-field__required">*</span>}
      </label>
      {children}
      {hint && <p className="hevi-field__hint">{hint}</p>}
    </div>
  );
}

/* ── ActionButton ───────────────────────────────────────────── */

interface ActionButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

export function ActionButton({
  variant = 'primary',
  size = 'md',
  loading = false,
  children,
  disabled,
  className = '',
  ...rest
}: ActionButtonProps) {
  return (
    <button
      type="button"
      className={`hevi-btn hevi-btn--${variant} hevi-btn--${size} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? '处理中…' : children}
    </button>
  );
}

/* ── PageShell ──────────────────────────────────────────────── */

interface PageShellProps {
  children: React.ReactNode;
  className?: string;
}

export function PageShell({ children, className = '' }: PageShellProps) {
  return <div className={`page-shell ${className}`}>{children}</div>;
}

/* ── SectionHeader ──────────────────────────────────────────── */

interface SectionHeaderProps {
  icon?: string;
  title: string;
  subtitle?: string;
  className?: string;
}

export function SectionHeader({ icon, title, subtitle, className = '' }: SectionHeaderProps) {
  return (
    <div className={`page-intro ${className}`}>
      <h1 className="page-intro__title">
        {icon && <span className="page-intro__icon">{icon}</span>}
        {title}
      </h1>
      {subtitle && <p className="page-intro__subtitle">{subtitle}</p>}
    </div>
  );
}

/* ── ResultBox ──────────────────────────────────────────────── */

interface ResultBoxProps {
  data: unknown;
  error?: string;
}

export function ResultBox({ data, error }: ResultBoxProps) {
  if (error) {
    return <div className="hevi-result hevi-result--error"><p>{error}</p></div>;
  }
  return (
    <div className="hevi-result">
      <h4 className="hevi-result__title">结果</h4>
      <pre className="hevi-result__json">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
