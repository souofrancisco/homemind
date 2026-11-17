const formatter = (options: Intl.DateTimeFormatOptions) => {
  const intl = new Intl.DateTimeFormat("pt-PT", options);
  return (value: string | number | Date) => intl.format(new Date(value));
};

export const formatHM = formatter({ hour: "2-digit", minute: "2-digit" });
export const formatHMS = formatter({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const formatDay = formatter({ dateStyle: "full" });
