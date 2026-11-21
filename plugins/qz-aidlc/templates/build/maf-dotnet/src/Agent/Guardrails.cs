using System.Text.RegularExpressions;

namespace OrderAgent;

/// <summary>
/// Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and
/// the reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same calls.
/// Input: a message that reads like an instruction to change how the agent works is refused before the model sees it;
/// payment card numbers and national ID numbers are masked, so the model, the trace and the logs never hold them.
/// Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
/// (Policy.BlockedTerms, empty by default) is replaced, never sent.
/// </summary>
public static class Guardrails
{
    public const string Refusal = "I can't act on that: it reads like an instruction to change how I work, not a question about an order. Ask me about an order instead.";
    public const string Withheld = "I can't send that reply. A person will follow up.";
    /// <summary>Shown before the first reply (EU AI Act Article 50(1)).</summary>
    public const string AiNotice = "You're chatting with an AI assistant, not a person.";

    private static readonly Regex Instruction = new(
        @"\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidelines|guardrails?)\b|\byou are now\b|\b(system|developer) prompt\b|\b(jailbreak|dan mode|developer mode)\b|\breveal\b[^.\n]{0,60}\b(prompt|instructions?|passwords?|secrets?|keys?|credentials?)\b",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex Card = new(@"\b(?:[0-9][ -]?){12,18}[0-9]\b", RegexOptions.CultureInvariant);
    private static readonly Regex NationalId = new(@"\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b", RegexOptions.CultureInvariant);

    public sealed record Screened(string Text, bool Blocked, List<string> Findings);

    private static bool Luhn(string digits)
    {
        int total = 0;
        bool alt = false;
        for (int i = digits.Length - 1; i >= 0; i--)
        {
            int n = (digits[i] - '0') * (alt ? 2 : 1);
            total += n > 9 ? n - 9 : n;
            alt = !alt;
        }
        return total % 10 == 0;
    }

    public static (string Text, List<string> Findings) Mask(string text)
    {
        List<string> found = [];
        string output = Card.Replace(text ?? "", m =>
        {
            string digits = Regex.Replace(m.Value, "[^0-9]", "");
            if (digits.Length is >= 13 and <= 19 && Luhn(digits))
            {
                found.Add("card number");
                return "[card number removed]";
            }
            return m.Value;
        });
        output = NationalId.Replace(output, _ =>
        {
            found.Add("ID number");
            return "[ID number removed]";
        });
        return (output, found);
    }

    public static Screened ScreenInput(string message)
    {
        if (Instruction.IsMatch(message ?? "")) return new Screened(Refusal, true, ["instruction-like input"]);
        var (text, found) = Mask(message ?? "");
        return new Screened(text, false, found);
    }

    public static Screened ScreenOutput(string reply)
    {
        var (text, found) = Mask(reply ?? "");
        if (Policy.BlockedTerms.Any(t => t.Length > 0 && text.Contains(t, StringComparison.OrdinalIgnoreCase)))
            return new Screened(Withheld, true, [.. found, "blocked term"]);
        return new Screened(text, false, found);
    }
}
